
# -*- coding: utf-8 -*-

import os
import logging
from pyramid.config import Configurator
from pyramid.session import SignedCookieSessionFactory
from pyramid.view import view_config
from pyramid.events import NewRequest, subscriber
from pyramid.httpexceptions import HTTPFound, HTTPInternalServerError
# NOTE: Authentication is logging in, while
# authorization is figuring out what you can do when logged in.
from pyramid.authentication import AuthTktAuthenticationPolicy
from pyramid.authorization import ACLAuthorizationPolicy
from waitress import serve
import psycopg2
from contextlib import closing
import datetime


DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id serial PRIMARY KEY,
    title VARCHAR (127) NOT NULL,
    text TEXT NOT NULL,
    created TIMESTAMP NOT NULL
)
"""

INSERT_ENTRY = """
INSERT INTO entries (title, text, created) VALUES (%s, %s, %s)
"""

SELECT_ENTRIES = """
SELECT id, title, text, created FROM entries ORDER BY created DESC
"""


logging.basicConfig()
log = logging.getLogger(__file__)


def connect_db(settings):
    """
    Return a connection to the configured database.
    """
    return psycopg2.connect(settings['db'])


def init_db():
    """
    Create database dables defined by DB_SCHEMA.

    Warning: This function will not update existing table definitions.
    """
    settings = {}
    settings['db'] = os.environ.get('DATABASE_URL',
                                    'dbname=pyramid_learning_journal'
                                    ' user=fried')
    with closing(connect_db(settings)) as db:
        db.cursor().execute(DB_SCHEMA)
        db.commit()


# This function opens a database connection for each client request.
@subscriber(NewRequest)
def open_connection(event):
    """
    Open a database connection for the request
    tied to the supplied event, and provide
    a finished_callback function to close it
    upon the return of the response to the client.
    """

    request = event.request
    settings = request.registry.settings
    request.db = connect_db(settings)
    # The request should close this DB connection
    # right before it's sent back to the client.
    # For this we use the handy add_finished_callback()
    # function that pyramid.events.NewRequest objects
    # provide for this purpose:
    request.add_finished_callback(close_connection)


def close_connection(request):
    """
    Close the database connection for this request.

    If there has been an error in the processing of the
    request, abort any open transactions.
    """

    db = getattr(request, 'db', None)
    if db is not None:
        # Snazzy! Keeps our database clean.
        if request.exception is not None:
            db.rollback()
        else:
            db.commit()
        request.db.close()


def main():
    """
    Create a configured WSGI app.
    """
    settings = {}
    settings['reload_all'] = os.environ.get('DEBUG', True)
    settings['debug_all'] = os.environ.get('DEBUG', True)
    settings['db'] = os.environ.get('DATABASE_URL',
                                    'dbname=pyramid_learning_journal'
                                    ' user=fried')
    settings['auth.username'] = os.environ.get('AUTH_USERNAME', 'admin')
    settings['auth.password'] = os.environ.get('AUTH_PASSWORD', 'secret')
    # "secret value for session signing"
    secret = os.environ.get('JOURNAL_SESSION_SECRET', 'itsaseekrit')
    # "secret value for auth tkt signing"
    auth_secret = os.environ.get('JOURNAL_AUTH_SECRET', 'anotherseekrit')
    session_factory = SignedCookieSessionFactory(secret)
    # "configuration setup"
    config = Configurator(
        settings=settings,
        session_factory=session_factory,
        authentication_policy=AuthTktAuthenticationPolicy(
            secret=auth_secret,
            hashalg='sha512'
        ),
        authorization_policy=ACLAuthorizationPolicy(),
    )
    config.include('pyramid_jinja2')
    config.add_route('home', '/')
    config.add_route('add', '/add')
    config.scan()
    app = config.make_wsgi_app()
    return app


def write_entry(request):
    """
    Write a single entry to the database.
    """
    title = request.params.get('title', None)
    text = request.params.get('text', None)
    created = datetime.datetime.utcnow()
    request.db.cursor().execute(INSERT_ENTRY, [title, text, created])


@view_config(route_name='home', renderer='templates/list.jinja2')
def read_entries(request):
    """
    Return a list of all entries as dictionaries.
    """
    cursor = request.db.cursor()
    cursor.execute(SELECT_ENTRIES)
    keys = ('id', 'title', 'text', 'created')
    entries = [dict(zip(keys, row)) for row in cursor.fetchall()]
    return {'entries': entries}


@view_config(route_name='add', request_method='POST')
def add_entry(request):
    try:
        write_entry(request)
    except psycopg2.Error:
        # "this will catch any errors generated by the database"
        return HTTPInternalServerError
    return HTTPFound(request.route_url('home'))


def do_login(request):
    username = request.params.get('username', None)
    password = request.params.get('password', None)
    # CRITICAL:
    # Do not distinguish between a bad password and a bad username!
    # To do so is to leak sensitive information.
    if not (username and password):
        raise ValueError('both username and password are required')

    settings = request.registry.settings
    if username == settings.get('auth.username', ''):
        if password == settings.get('auth.password', ''):
            return True
    return False


if __name__ == '__main__':
    app = main()
    port = os.environ.get('PORT', 5000)
    serve(app, host='0.0.0.0', port=port)
