# -*- coding: utf-8 -*-
from contextlib import closing
from pyramid import testing
import pytest
import datetime

from journal import connect_db
from journal import DB_SCHEMA
from journal import INSERT_ENTRY


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

