#! /usr/bin/env py.test

import sys


def test_fail_later(testdir):
    testdir.makepyfile("""
pytest_plugins = "pytest_twisted"

from twisted.internet import reactor, defer

def test_fail():
    def doit():
        try:
            1 / 0
        except:
            d.errback()

    d = defer.Deferred()
    reactor.callLater(0.01, doit)
    return d
""")
    rr = testdir.run(sys.executable, "-m", "pytest")
    outcomes = rr.parseoutcomes()
    assert outcomes.get("failed") == 1


def test_succeed_later(testdir):
    testdir.makepyfile("""
from twisted.internet import reactor, defer

def test_succeed():
    d = defer.Deferred()
    reactor.callLater(0.01, d.callback, 1)
    return d
""")
    rr = testdir.run(sys.executable, "-m", "pytest", "--twisted")
    outcomes = rr.parseoutcomes()
    assert outcomes.get("passed") == 1


def test_non_deferred(testdir):
    testdir.makepyfile("""
pytest_plugins = "pytest_twisted"

from twisted.internet import reactor, defer

def test_succeed():
    return 42
""")
    rr = testdir.run(sys.executable, "-m", "pytest")
    outcomes = rr.parseoutcomes()
    assert outcomes.get("passed") == 1


def test_exception(testdir):
    testdir.makepyfile("""
pytest_plugins = "pytest_twisted"

def test_more_fail():
    raise RuntimeError("foo")
""")
    rr = testdir.run(sys.executable, "-m", "pytest")
    outcomes = rr.parseoutcomes()
    assert outcomes.get("failed") == 1


def test_inlineCallbacks(testdir):
    testdir.makepyfile("""
from twisted.internet import reactor, defer
import pytest

@pytest.fixture(scope="module",
                params=["fs", "imap", "web"])
def foo(request):
    return request.param


@pytest.inlineCallbacks
def test_succeed(foo):
    yield defer.succeed(foo)
    if foo == "web":
        raise RuntimeError("baz")
""")
    rr = testdir.run(sys.executable, "-m", "pytest", "--twisted", "-v")
    outcomes = rr.parseoutcomes()
    assert outcomes.get("passed") == 2
    assert outcomes.get("failed") == 1


def test_inlineCallbacks(testdir):
    testdir.makepyfile("""
import pytest, greenlet

MAIN = None


@pytest.fixture(scope="session", autouse=True)
def set_MAIN(request, twisted_greenlet):
    global MAIN
    MAIN = twisted_greenlet


def test_MAIN():
    assert MAIN is not None
    assert MAIN is greenlet.getcurrent()

""")
    rr = testdir.run(sys.executable, "-m", "pytest", "--twisted", "-v")
    outcomes = rr.parseoutcomes()
    assert outcomes.get("passed") == 1
