#! /usr/bin/env py.test

import sys


def test_fail_later(testdir):
    testdir.makepyfile("""
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
    rr = testdir.run(sys.executable, "-m", "pytest")
    outcomes = rr.parseoutcomes()
    assert outcomes.get("passed") == 1


def test_non_deferred(testdir):
    testdir.makepyfile("""
        from twisted.internet import reactor, defer

        def test_succeed():
            return 42
    """)
    rr = testdir.run(sys.executable, "-m", "pytest")
    outcomes = rr.parseoutcomes()
    assert outcomes.get("passed") == 1


def test_exception(testdir):
    testdir.makepyfile("""
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
        import pytest_twisted

        @pytest.fixture(scope="module",
                        params=["fs", "imap", "web"])
        def foo(request):
            return request.param


        @pytest_twisted.inlineCallbacks
        def test_succeed(foo):
            yield defer.succeed(foo)
            if foo == "web":
                raise RuntimeError("baz")
    """)
    rr = testdir.run(sys.executable, "-m", "pytest", "-v")
    outcomes = rr.parseoutcomes()
    assert outcomes.get("passed") == 2
    assert outcomes.get("failed") == 1


def test_twisted_greenlet(testdir):
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
    rr = testdir.run(sys.executable, "-m", "pytest", "-v")
    outcomes = rr.parseoutcomes()
    assert outcomes.get("passed") == 1


def test_blocon_in_hook(testdir):
    testdir.makeconftest("""
        import pytest
        import pytest_twisted as pt
        from twisted.internet import reactor, defer

        def pytest_configure(config):
            d = defer.Deferred()
            reactor.callLater(0.01, d.callback, 1)
            pt.blockon(d)
    """)
    testdir.makepyfile("""
        from twisted.internet import reactor, defer

        def test_succeed():
            d = defer.Deferred()
            reactor.callLater(0.01, d.callback, 1)
            return d
    """)
    rr = testdir.run(sys.executable, "-m", "pytest", "-v")
    outcomes = rr.parseoutcomes()
    assert outcomes.get("passed") == 1


def test_pytest_from_reactor_thread(testdir):
    testdir.makepyfile("""
        import pytest
        import pytest_twisted as pt
        from twisted.internet import reactor, defer

        @pytest.fixture
        def fix():
            d = defer.Deferred()
            reactor.callLater(0.01, d.callback, 42)
            return pt.blockon(d)

        def test_simple(fix):
            assert fix == 42

        @pt.inlineCallbacks
        def test_fail():
            d = defer.Deferred()
            reactor.callLater(0.01, d.callback, 1)
            yield d
            assert False
    """)
    testdir.makepyfile(runner="""
        import pytest

        from twisted.internet import reactor
        from twisted.internet.defer import inlineCallbacks
        from twisted.internet.threads import deferToThread

        codes = []

        @inlineCallbacks
        def main():
            try:
                codes.append((yield deferToThread(pytest.main, ['-k simple'])))
                codes.append((yield deferToThread(pytest.main, ['-k fail'])))
            finally:
                reactor.stop()

        if __name__ == '__main__':
            reactor.callLater(0, main)
            reactor.run()
            codes == [0, 1] or exit(1)
    """)
    # check test file is ok in standalone mode:
    rr = testdir.run(sys.executable, "-m", "pytest", "-v")
    outcomes = rr.parseoutcomes()
    assert outcomes.get("passed") == 1
    assert outcomes.get("failed") == 1
    # test embedded mode:
    assert testdir.run(sys.executable, "runner.py").ret == 0
