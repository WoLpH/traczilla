import setuptools

setuptools.setup(
    name='trellotrac',
    version='1.0',
    author='Rick van Hattem',
    author_email='wolph@wol.ph',
    description='Script for bidirectional sync between Trello and Trac',
    url='https://github.com/WoLpH/trellotrac',
    license='BSD',
    packages=['trello'],
    entry_points={
        'trac.plugins': [
            'trello = trello.trello',
        ],
    },
    install_requires=['trolly==1.0.0'],
    dependency_links=['git+https://github.com/plish/Trolly.git#egg=trolly'],
    package_data={'trello': [
        'templates/*.html',
        'htdocs/css/*.css',
        'htdocs/images/*',
    ]},
)
