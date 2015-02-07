# -*- coding: utf-8 -*-
from contextlib import closing
from pyramid import testing
import pytest
import datetime
import os

from journal import connect_db
from journal import DB_SCHEMA
from journal import INSERT_ENTRY

from cryptacular.bcrypt import BCRYPTPasswordManager


TEST_DSN = 'dbname=test_pyramid_learning_journal user=fried'


def init_db(settings):
    with closing(connect_db(settings)) as db:
        db.cursor().execute(DB_SCHEMA)
        db.commit()


def clear_db(settings):
    with closing(connect_db(settings)) as db:
        db.cursor().execute("DROP TABLE entries")
        db.commit()


def clear_entries(settings):
    with closing(connect_db(settings)) as db:
        db.cursor().execute("DELETE FROM entries")
        db.commit()


def run_query(db, query, params=(), get_results=True):
    cursor = db.cursor()
    cursor.execute(query, params)
    db.commit()
    results = None
    if get_results:
        results = cursor.fetchall()
    return results


@pytest.fixture(scope='session')
def db(request):
    """
    Set up and tear down a database.
    """
    settings = {'db': TEST_DSN}
    init_db(settings)

    def cleanup():
        clear_db(settings)

    request.addfinalizer(cleanup)
    return settings


@pytest.yield_fixture(scope='function')
def req_context(db, request):
    """
    Mock a request with a database attached.
    """
    settings = db
    req = testing.DummyRequest()

    # "Because yield preserves internal state,
    # the entire test happens inside the context manager scope!"
    with closing(connect_db(settings)) as db:
        req.db = db
        req.exception = None
        yield req

        # "after a test has run, we clear out entries for isolation"
        clear_entries(settings)


def test_write_entry(req_context):
    from journal import write_entry
    fields = ('title', 'text')
    expected = ('Test Title', 'Test Text')
    req_context.params = dict(zip(fields, expected))

    # "assert that there are no entries when we start"
    rows = run_query(req_context.db, "SELECT * FROM entries")
    assert len(rows) == 0

    result = write_entry(req_context)
    # "manually commit so we can see the entry on query"
    req_context.db.commit()

    rows = run_query(req_context.db, "SELECT title, text FROM entries")
    assert len(rows) == 1
    actual = rows[0]
    for idx, val in enumerate(expected):
        assert val == actual[idx]


def test_read_entries_empty(req_context):
    # "call the function under test"
    from journal import read_entries
    result = read_entries(req_context)
    # "make assertions about the result"
    assert 'entries' in result
    assert len(result['entries']) == 0


def test_read_entries(req_context):
    # "prepare data for testing"
    now = datetime.datetime.utcnow()
    expected = ('Test Title', 'Test Text', now)
    run_query(req_context.db, INSERT_ENTRY, expected, False)
    # "call the function under test"
    from journal import read_entries
    result = read_entries(req_context)
    # "make assertions about the result"
    assert 'entries' in result
    assert len(result['entries']) == 1
    for entry in result['entries']:
        assert expected[0] == entry['title']
        assert expected[1] == entry['text']
        for key in 'id', 'created':
            assert key in entry


@pytest.fixture(scope='function')
def app(db):
    from journal import main
    from webtest import TestApp
    os.environ['DATABASE_URL'] = TEST_DSN
    app = main()
    return TestApp(app)


def test_empty_listing(app):
    response = app.get('/')
    assert response.status_code == 200
    actual = response.body
    expected = 'No entries here so far'
    assert expected in actual


@pytest.fixture(scope='function')
def entry(db, request):
    """provide a single entry in the database"""
    settings = db
    now = datetime.datetime.utcnow()
    expected = ('Test Title', 'Test Text', now)
    with closing(connect_db(settings)) as db:
        run_query(db, INSERT_ENTRY, expected, False)
        db.commit()

    def cleanup():
        clear_entries(settings)

    request.addfinalizer(cleanup)

    return expected


def test_listing(app, entry):
    response = app.get('/')
    assert response.status_code == 200
    actual = response.body
    for expected in entry[:2]:
        assert expected in actual


def test_post_to_add_view(app):
    entry_data = {
        'title': 'Hello there',
        'text': 'This is a post',
    }
    response = app.post('/add', params=entry_data, status='3*')
    redirected = response.follow()
    actual = redirected.body
    for expected in entry_data.values():
        assert expected in actual


@pytest.fixture(scope='function')
def auth_req(request):
    # Push it through the ciphertube
    manager = BCRYPTPasswordManager()
    settings = {
        'auth.username': 'admin',
        'auth.password': manager.encode('secret'),
    }
    testing.setUp(settings=settings)
    req = testing.DummyRequest()

    def cleanup():
        testing.tearDown()

    request.addfinalizer(cleanup)

    return req


def test_do_login_success(auth_req):
    from journal import do_login
    auth_req.params = {'username': 'admin', 'password': 'secret'}
    assert do_login(auth_req)


def test_do_login_bad_pass(auth_req):
    from journal import do_login
    auth_req.params = {'username': 'admin', 'password': 'wrong'}
    assert not do_login(auth_req)


def test_do_login_bad_user(auth_req):
    from journal import do_login
    auth_req.params = {'username': 'bad', 'password': 'secret'}
    assert not do_login(auth_req)


def test_do_login_missing_params(auth_req):
    from journal import do_login
    for params in ({'username': 'admin'}, {'password': 'secret'}):
        auth_req.params = params
        with pytest.raises(ValueError):
            do_login(auth_req)
