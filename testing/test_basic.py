#! /usr/bin/env py.test

import sys
import textwrap

import pytest


def assert_outcomes(run_result, outcomes):
    formatted_output = format_run_result_output_for_assert(run_result)

    try:
        outcomes = run_result.parseoutcomes()
    except ValueError:
        assert False, formatted_output

    for name, value in outcomes.items():
        assert outcomes.get(name) == value, formatted_output


def format_run_result_output_for_assert(run_result):
    return textwrap.dedent('''\

        ---- stdout
        {0}
        ---- stderr
        {1}
        ----''').format(
        run_result.stdout.str(),
        run_result.stderr.str(),
    )


def skip_if_reactor_not(expected_reactor):
    actual_reactor = pytest.config.getoption('reactor')
    return pytest.mark.skipif(
        actual_reactor != expected_reactor,
        reason='reactor is {0} not {1}'.format(
            actual_reactor,
            expected_reactor,
        ),
    )


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
    assert_outcomes(rr, {'failed': 1})


def test_succeed_later(testdir):
    testdir.makepyfile("""
        from twisted.internet import reactor, defer

        def test_succeed():
            d = defer.Deferred()
            reactor.callLater(0.01, d.callback, 1)
            return d
    """)
    rr = testdir.run(sys.executable, "-m", "pytest")
    assert_outcomes(rr, {'passed': 1})


def test_non_deferred(testdir):
    testdir.makepyfile("""
        from twisted.internet import reactor, defer

        def test_succeed():
            return 42
    """)
    rr = testdir.run(sys.executable, "-m", "pytest")
    assert_outcomes(rr, {'passed': 1})


def test_exception(testdir):
    testdir.makepyfile("""
        def test_more_fail():
            raise RuntimeError("foo")
    """)
    rr = testdir.run(sys.executable, "-m", "pytest")
    assert_outcomes(rr, {'failed': 1})


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
    assert_outcomes(rr, {'passed': 2, 'failed': 1})


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
    assert_outcomes(rr, {'passed': 1})


@skip_if_reactor_not('default')
def test_blockon_in_hook(testdir):
    testdir.makeconftest("""
        import pytest_twisted as pt
        from twisted.internet import reactor, defer

        def pytest_configure(config):
            pt.init_default_reactor()
            d, d2 = defer.Deferred(), defer.Deferred()
            reactor.callLater(0.01, d.callback, 1)
            reactor.callLater(0.02, d2.callback, 1)
            pt.blockon(d)
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
    assert_outcomes(rr, {'passed': 1})


@skip_if_reactor_not('default')
def test_wrong_reactor(testdir):
    testdir.makepyfile("""
        import twisted.internet.reactor
        twisted.internet.reactor = None

        def test_succeed():
            pass
    """)
    rr = testdir.run(sys.executable, "-m", "pytest", "-v")
    assert 'WrongReactorAlreadyInstalledError' in rr.stdout.str()
    assert_outcomes(rr, {'error': 1})


@skip_if_reactor_not('qt5reactor')
def test_blockon_in_hook_with_qt5reactor(testdir):
    testdir.makeconftest("""
    import pytest_twisted as pt
    import pytestqt
    from twisted.internet import defer


    def pytest_configure(config):
        qapp = pytestqt.plugin.qapp(pytestqt.plugin.qapp_args())

        pt.init_qt5_reactor(qapp)
        d = defer.Deferred()

        from twisted.internet import reactor
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
    assert_outcomes(rr, {'passed': 1})


@skip_if_reactor_not('qt5reactor')
def test_wrong_reactor_with_qt5reactor(testdir):
    testdir.makepyfile("""
        import twisted.internet.default
        twisted.internet.default.install()

        def test_succeed():
            pass
    """)
    rr = testdir.run(
        sys.executable, "-m", "pytest", "-v", "--reactor=qt5reactor"
    )
    assert 'WrongReactorAlreadyInstalledError' in rr.stdout.str()
    assert_outcomes(rr, {'error': 1})


def test_pytest_from_reactor_thread(testdir):
    testdir.makepyfile("""
        import pytest
        import pytest_twisted
        from twisted.internet import reactor, defer

        @pytest.fixture
        def fix():
            d = defer.Deferred()
            reactor.callLater(0.01, d.callback, 42)
            return pytest_twisted.blockon(d)

        def test_simple(fix):
            assert fix == 42

        @pytest_twisted.inlineCallbacks
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
    assert_outcomes(rr, {'passed': 1, 'failed': 1})
    # test embedded mode:
    assert testdir.run(sys.executable, "runner.py").ret == 0
