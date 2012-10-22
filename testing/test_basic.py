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
