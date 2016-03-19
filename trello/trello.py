# vim: set fileencoding=utf8 :
import re
import json
import pprint
import functools

import trolly

from trac.web import IRequestHandler
from trac.ticket.api import ITicketChangeListener
from trac.ticket import Ticket
from trac import core
from trac import config


LABELS = {
    '3TU.DC': {
        'component': 'Datacentrum',
    },
    'Zandmotor': {
        'component': 'Zandmotor',
    },
    'Datacite': {
        'component': 'Datacite',
    },
    'P1': {
        'priority': 'highest',
    },
    'P2': {
        'priority': 'high',
    },
    'P3': {
        'priority': 'normal',
    },
    'P4': {
        'priority': 'low',
    },
    'P5': {
        'priority': 'lowest',
    },
}


def to_list(function):
    @functools.wraps(function)
    def _to_list(*args, **kwargs):
        return list(function(*args, **kwargs))
    return _to_list


class TrelloHandler(object):
    def __init__(self, plugin, **kwargs):
        self.plugin = plugin
        self.env = plugin.env
        self.action = dict(data=dict())
        self.__dict__.update(**kwargs)

    def dispatch(self):
        method_name = self.action['type']
        method = getattr(self, method_name, None)
        if method:
            self.env.log.info('Calling %r from Trello:\n%s', method_name,
                              self.data)
            return method(self.data)
        else:
            raise RuntimeError('Unknown method %r' % method_name)

    def get_trello_url(self, prefix=None, shortLink=None, name=None, **kwargs):
        name = name or self.data['name']
        shortLink = shortLink or self.data['shortLink']

        if not prefix:
            if 'card' in self.data:
                prefix = 'c'
            elif 'board' in self.data:
                prefix = 'b'
            else:
                raise RuntimeError('Unable to get url for %r' % self.data,
                                   self.data)

        return 'https://trello.com/%(prefix)s/%(shortLink)s/%(name)s' % dict(
            prefix=prefix,
            shortLink=shortLink,
            name=name,
        )

    @property
    def data(self):
        'Shortcut to action[data]'
        return self.action['data']

    @property
    def name(self):
        return self.data['card']['name']

    def addLabelToCard(self, data):
        ticket = self.get_ticket(**data['card'])
        if data['text'] in LABELS:
            ticket.values.update(LABELS[data['text']])

            board_id = data['board']['id']
            if not ticket.exists:
                create_from_boards = self.plugin.create_from_boards
                # Skip boards that are not allowed
                if create_from_boards and board_id not in create_from_boards:
                    return

                assert ticket.values['trello']

                with self.env.db_transaction as db:
                    client = self.plugin.get_trello_client()
                    board = client.get_board(board_id)
                    card = board.get_card(board_id)

                    ticket.insert(db=db)
                    self.update_card(card, ticket)
        else:
            ticket.values['keywords'] += ' %s' % data['text']

        if ticket.exists:
            ticket.save_changes(self.action['memberCreator']['username'],
                                '[trello] Added label %s' % data['text'])

    def removeLabelFromCard(self, data):
        # if data['text']
        pass

    def createCard(self, data):
        pass

    def updateCard(self, data):
        if 'listBefore' in data or 'listAfter' in data:
            return self.moveCard(data, data['listBefore'], data['listAfter'])
        elif 'old' in data and 'pos' in data['old']:
            pass  # No need to handle reorder operations
        else:
            self.env.log.warn('Unsupported action %s:\n%s',
                              self.action['type'],
                              pprint.pformat(data))

    def deleteCard(self, data):
        pass

    def commentCard(self, data):
        comment = self.data['text']
        if not self.get_bug_id(self.name):
            # Update is definitely needed
            pass
        elif comment.startswith('[trac]') or comment.startswith('[trello]'):
            # Skip these
            return

        self.update_ticket(data=data, comment=comment)

    def updateComment(self, data):
        pass

    def deleteComment(self, data):
        pass

    def get_status(self, status, list_):
        name = list_['name'].lower()
        if name == 'to do':
            if status == 'new':
                return status
            else:
                return 'reopened'

        elif name in ('doing', 'testing'):
            return name.replace(' ', '')
        elif name.startswith('done'):
            return 'done'
        else:
            self.env.log.info('No status available for %r' % name)
            return status

    def moveCard(self, data, from_, to):
        self.update_ticket(data, to)

    def moveCardFromBoard(self, data, from_, to):
        self.env.log.info('from: %r', from_)
        self.env.log.info('to: %r', to)
        self.update_ticket(data, to)

    def update_card(self, card, ticket):
        name = self.plugin.get_trello_name(ticket)
        description = self.plugin.get_trello_description(ticket)

        update = False
        if card.name != name:
            update = True

        if card.desc != description:
            update = True

        if update:
            # Convert to utf-8
            if isinstance(name, str):
                name = name.decode('utf-8', 'replace')

            if isinstance(description, str):
                description = description.decode('utf-8', 'replace')

            card.update_card(dict(
                name=name.encode('utf-8', 'replace'),
                desc=description.encode('utf-8', 'replace'),
            ))

    def update_ticket(self, data, list_=None, comment=''):
        bug_id = self.get_bug_id(self.name)
        if not bug_id:
            return

        card = data['card']
        name = card['name']
        creator = self.action.get('memberCreator', {})

        ticket = self.get_ticket(self.name)
        username = creator.get('username') or ticket.values['owner']

        if list_:
            ticket.values['status'] = self.get_status(
                ticket.values['status'], list_)
        ticket.values['owner'] = username
        ticket.values['resolution'] = ''
        ticket.values['trello'] = self.get_trello_url(**data['card'])
        ticket.values['summary'] = self.get_name()

        expected_points = self.get_estimate(name)
        if expected_points:
            ticket.values['expected_points'] = str(expected_points)

        actual_points = self.get_time_spent(name)
        if actual_points:
            ticket.values['actual_points'] = str(actual_points)

        comment = '[trello] Changed status: [[%s|%s]]\n%s' % (
            self.get_trello_url(**data['card']), name, comment)
        ticket.save_changes(username, comment)
        return ticket

    def get_name(self):
        name = self.name
        name = re.sub('#\d{4}', '', name)
        name = re.sub('\(\d{1,2}\)', '', name)
        name = re.sub('\[\d{1,2}\]', '', name)
        name = re.sub('^[ -]+', '', name)
        name = re.sub('[ -]+$', '', name)
        return name

    def get_ticket(self, name, shortLink=None, **kwargs):
        bug_id = self.get_bug_id(name)
        if bug_id:
            ticket = Ticket(self.env, bug_id)
        else:
            ticket = Ticket(self.env)
            ticket.values['summary'] = name
            ticket.values['trello'] = self.get_trello_url(
                prefix='c', shortLink=shortLink, name=name)

        return ticket

    def get_bug_id(self, name):
        match = re.search(r'(\d{4})', name)
        if match and 1000 < int(match.group(1)) < 3000:
            return int(match.group(1))
        else:
            self.env.log.debug('Card %r has no bug-id', name)

    def get_partial(self, name=None):
        name = name or self.name
        match = re.search(r'\s*- (deel \d{1}[^\[(]*)', name)
        if match:
            return match.group(1)

    def get_estimate(self, name=None):
        name = name or self.name
        match = re.search(r'\((\d{1,2})\)', name)
        if match and 1 <= int(match.group(1)) < 40:
            return int(match.group(1))

    def get_time_spent(self, name=None):
        name = name or self.name
        match = re.search(r'\[(\d{1,2})\]', name)
        if match and 1 <= int(match.group(1)) < 40:
            return int(match.group(1))


class TrelloTracPlugin(core.Component):
    api_key = config.Option('trello', 'api_key', doc='Trello API key')
    api_secret = config.Option('trello', 'api_secret', doc='Trello API secret')
    token = config.Option('trello', 'token', doc='Trello token')
    token_secret = config.Option(
        'trello', 'token_secret', doc='Trello token secret')
    organisation_ids = config.ListOption(
        'trello', 'organisations',
        doc='Trello organisation IDs. Defaults to all')
    board_ids = config.ListOption(
        'trello', 'boards',
        doc='Trello board IDs. Defaults to all within the organisations')
    create_from_boards = config.ListOption(
        'trello', 'create_from_boards',
        doc='Allow ticket creation from these boards. Defaults to all')

    trello_ips = config.ListOption('trello', 'trello_ips', default=','.join((
        '107.23.104.115',
        '107.23.149.70',
        '54.152.166.250',
        '54.164.77.56',
    )), doc='Trello server IPs for extra authentication')

    core.implements(
        IRequestHandler,
        ITicketChangeListener)

    # IRequestHandler requires a request matching method
    def match_request(self, req):
        # Only admins and Trello IPs
        whitelisted = req.remote_addr in self.trello_ips
        admin = 'TRAC_ADMIN' in req.perm
        view = self.views.get(req.path_info)
        return view and (admin or whitelisted)

    # IRequestHandler requires a request handling method
    def process_request(self, req):
        return self.views[req.path_info](self, req)

    def process_update(self, req):
        for board in self.get_boards():
            for card in board.get_cards():
                print 'updating', card
                data = dict(
                    data=dict(
                        card=card.data,
                    ),
                )

                handler = TrelloHandler(self, action=data)
                ticket = handler.update_ticket(data['data'])
                if ticket and ticket.id:
                    handler.update_card(card, ticket)
        req.send('Updating...', 'text/plain')

    def process_webhook(self, req):
        raw_body = req.read().strip()
        if not raw_body:
            req.send('No body available', 'text/plain')
            return

        body = json.loads(raw_body)
        action = TrelloHandler(self, **body)
        action.dispatch()

        req.send('All good', 'text/plain')

    views = {
        '/trello/webhook': process_webhook,
        '/trello/update': process_update,
    }

    def get_trello_client(self):
        return trolly.Client(
            self.api_key,
            self.token,
        )

    def get_organisations(self, client=None):
        client = client or self.get_trello_client()
        for organisation_id in self.organisations_ids:
            yield client.get_organisation(organisation_id)

    def get_boards(self):
        for organisation in self.get_organisations():
            for board in organisation.get_boards():
                if board.id in self.board_ids or not self.board_ids:
                    yield board
                else:
                    self.env.log.info('Skipping %r', board)

    def get_ticket_board_id(self, ticket):
        component = ticket.values['component'].lower()
        return self.config.get('trello-component', component)

    def get_ticket_board(self, ticket):
        board_id = self.get_ticket_board_id(ticket)
        for board in self.get_boards():
            if board.id == board_id:
                return board

    def get_new_list(self, ticket):
        board = self.get_ticket_board(ticket)
        for list_ in board.get_lists():
            if list_.name.lower().startswith('new'):
                return list_

    def get_filtered_description(self, ticket):
        for line in ticket.values.get('description', '').split('\n'):
            if line.startswith('[trac'):
                continue
            elif line.startswith('[trello'):
                continue
            yield line.rstrip()

    def get_trello_description(self, ticket):
        description = '''
        [Trac \#%(id)s](https://trac.3tudc-libbuild.tudelft.nl/ticket/%(id)s)
        %(description)s''' % dict(
            id=ticket.id,
            description='\n'.join(self.get_filtered_description(ticket)),
        )

        return description.strip()

    def get_trello_name(self, ticket):
        parts = []
        parts.append('#%s' % ticket.id)
        if ticket.values.get('expected_points'):
            parts.append('(%d)' % int(ticket.values['expected_points']))
        if ticket.values.get('actual_points'):
            parts.append('[%d]' % int(ticket.values['actual_points']))
        parts.append('-')
        parts.append(ticket.values['summary'])
        return ' '.join(parts)

    def ticket_created(self, ticket):
        self.env.log.info('ticket created: %r', ticket.__dict__)

        new_list = self.get_new_list(ticket)
        new_list.add_card(dict(
            name=self.get_trello_name(ticket),
            desc=self.get_trello_description(ticket),
        ))

    def ticket_changed(self, ticket, comment, author, old_values):
        if comment.startswith('[trac]') or comment.startswith('[trello]'):
            return

        client = self.get_trello_client()

        shortlink_match = re.match('.*trello.com/c/([^/]+)/.*',
                                   ticket.values['trello'])

        shortlink = None
        if shortlink_match:
            shortlink = shortlink_match.group(1)
        else:
            search = client.fetch_json(uri_path='/search/', query_params=dict(
                modelTypes='cards',
                query=ticket.id,
            ))
            for card in search.get('cards', []):
                if card['name'].startswith('#%04d '):
                    shortlink = card['shortlink']
                    ticket.trello = card['url']
                    ticket.save_changes(
                        author, '[trello] Updated trello url to %(url)s' % card)
                    shortlink = card['shortLink']
                    break

        if not shortlink:
            self.env.log.warn('No Trello card found for %r', ticket)

        self.env.log.info('Adding comment from %r on %r to trello', author,
                          ticket)
        card = client.get_card(shortlink)
        card.add_comment(
            '[trac][By %s](%sticket/%s)\n%s' %
            (author, self.config.get('project', 'url'), ticket.id, comment))

    def getLinkByTicketId(self, idTicket):
        host = self.config.get('project', 'url')
        link = host + 'ticket/' + str(idTicket)
        return link

    def ticket_deleted(self, ticket):
        pass

