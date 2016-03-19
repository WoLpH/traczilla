Plugin to synchronize Trello and Trac. Expects that the Agilo for Trac package
is installed. 

To create the webhooks (use the Trello sandbox for that):

..
    var success = function(successMsg) {
        asyncOutput(successMsg);
    };

    var error = function(errorMsg) {
        asyncOutput(errorMsg);
    };

    // List of boards, only the ID is important here
    var boards = [
        {
            "name": "board name just for representation",
            "id": "123456789012345678901234"
        {
    ]

    for(var i=0; i<boards.length; i++){
        var board = boards[i];
        var parameters = {
            description: board.name + ' webhook',
            callbackURL: 'https://your.trac.host/trello/webhook',
            idModel: board.id
        };
        console.log(parameters);
        Trello.post('webhooks/', parameters, success, error);
    });

To remove **all** webhooks on your acccount:

..

    var success = function(successMsg) {
        asyncOutput(successMsg);
        for(var i=0; i<successMsg.length; i++){
            var webhooks = successMsg[i].webhooks;
            for(var j=0; j<webhooks.length; j++){
                console.log(webhooks[j]);
                Trello.delete('webhooks/' + webhooks[j].id);
            }
        }
    };

    var error = function(errorMsg) {
      asyncOutput(errorMsg);
    };

    Trello.get('/members/me/tokens?webhooks=true', success, error);

To configure, add something along these lines in your configuration file:

..
    [trello]
    api_key = ...
    token = ...
    # Allow creation from these boards
    create_from_boards = board-id, board-id
    # Which organisations to index
    organisations = organisation-id, organisation-id

    [trello-component]
    trac-component-name = trello-board-id
