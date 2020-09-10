import sys
import textwrap

import pytest


# https://docs.python.org/3/whatsnew/3.5.html#pep-492-coroutines-with-async-and-await-syntax
ASYNC_AWAIT = sys.version_info >= (3, 5)

# https://docs.python.org/3/whatsnew/3.6.html#pep-525-asynchronous-generators
ASYNC_GENERATORS = sys.version_info >= (3, 6)

timeout = 15


# https://github.com/pytest-dev/pytest/issues/6505
def force_plural(name):
    if name in {"error", "warning"}:
        return name + "s"

    return name


def assert_outcomes(run_result, outcomes):
    formatted_output = format_run_result_output_for_assert(run_result)

    try:
        result_outcomes = run_result.parseoutcomes()
    except ValueError:
        assert False, formatted_output

    normalized_result_outcomes = {
        force_plural(name): outcome
        for name, outcome in result_outcomes.items()
        if name != "seconds"
    }

    assert normalized_result_outcomes == outcomes, formatted_output


def format_run_result_output_for_assert(run_result):
    tpl = """
    ---- stdout
    {}
    ---- stderr
    {}
    ----
    """
    return textwrap.dedent(tpl).format(
        run_result.stdout.str(), run_result.stderr.str()
    )


@pytest.fixture(name="default_conftest", autouse=True)
def _default_conftest(testdir):
    testdir.makeconftest(textwrap.dedent("""
    import pytest
    import pytest_twisted


    @pytest.hookimpl(tryfirst=True)
    def pytest_configure(config):
        pytest_twisted._use_asyncio_selector_if_required(config=config)
    """))


def skip_if_reactor_not(request, expected_reactor):
    actual_reactor = request.config.getoption("reactor", "default")
    if actual_reactor != expected_reactor:
        pytest.skip(
            "reactor is {} not {}".format(actual_reactor, expected_reactor),
        )


def skip_if_no_async_await():
    return pytest.mark.skipif(
        not ASYNC_AWAIT,
        reason="async/await syntax not supported on Python <3.5",
    )


def skip_if_no_async_generators():
    return pytest.mark.skipif(
        not ASYNC_GENERATORS,
        reason="async generators not support on Python <3.6",
    )


@pytest.fixture
def cmd_opts(request):
    reactor = request.config.getoption("reactor", "default")
    return (
        sys.executable,
        "-m",
        "pytest",
        "-v",
        "--reactor={}".format(reactor),
    )


def test_inline_callbacks_in_pytest():
    assert hasattr(pytest, 'inlineCallbacks')


@pytest.mark.parametrize(
    'decorator, should_warn',
    (
        ('pytest.inlineCallbacks', True),
        ('pytest_twisted.inlineCallbacks', False),
    ),
)
def test_inline_callbacks_in_pytest_deprecation(
        testdir,
        cmd_opts,
        decorator,
        should_warn,
):
    import_path, _, _ = decorator.rpartition('.')
    test_file = """
    import {import_path}

    def test_deprecation():
        @{decorator}
        def f():
            yield 42
    """.format(import_path=import_path, decorator=decorator)
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)

    expected_outcomes = {"passed": 1}
    if should_warn:
        expected_outcomes["warnings"] = 1

    assert_outcomes(rr, expected_outcomes)


def test_blockon_in_pytest():
    assert hasattr(pytest, 'blockon')


@pytest.mark.parametrize(
    'function, should_warn',
    (
        ('pytest.blockon', True),
        ('pytest_twisted.blockon', False),
    ),
)
def test_blockon_in_pytest_deprecation(
        testdir,
        cmd_opts,
        function,
        should_warn,
):
    import_path, _, _ = function.rpartition('.')
    test_file = """
    import warnings

    from twisted.internet import reactor, defer
    import pytest
    import {import_path}

    @pytest.fixture
    def foo(request):
        d = defer.Deferred()
        d.callback(None)
        {function}(d)

    def test_succeed(foo):
        pass
    """.format(import_path=import_path, function=function)
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)

    expected_outcomes = {"passed": 1}
    if should_warn:
        expected_outcomes["warnings"] = 1

    assert_outcomes(rr, expected_outcomes)


def test_fail_later(testdir, cmd_opts):
    test_file = """
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
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"failed": 1})


def test_succeed_later(testdir, cmd_opts):
    test_file = """
    from twisted.internet import reactor, defer

    def test_succeed():
        d = defer.Deferred()
        reactor.callLater(0.01, d.callback, 1)
        return d
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 1})


def test_non_deferred(testdir, cmd_opts):
    test_file = """
    from twisted.internet import reactor, defer

    def test_succeed():
        return 42
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 1})


def test_exception(testdir, cmd_opts):
    test_file = """
    def test_more_fail():
        raise RuntimeError("foo")
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"failed": 1})


@pytest.fixture(
    name="empty_optional_call",
    params=["", "()"],
    ids=["no call", "empty call"],
)
def empty_optional_call_fixture(request):
    return request.param


def test_inlineCallbacks(testdir, cmd_opts, empty_optional_call):
    test_file = """
    from twisted.internet import reactor, defer
    import pytest
    import pytest_twisted

    @pytest.fixture(scope="module", params=["fs", "imap", "web"])
    def foo(request):
        return request.param

    @pytest_twisted.inlineCallbacks{optional_call}
    def test_succeed(foo):
        yield defer.succeed(foo)
        if foo == "web":
            raise RuntimeError("baz")
    """.format(optional_call=empty_optional_call)
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 2, "failed": 1})


@skip_if_no_async_await()
def test_async_await(testdir, cmd_opts, empty_optional_call):
    test_file = """
    from twisted.internet import reactor, defer
    import pytest
    import pytest_twisted

    @pytest.fixture(scope="module", params=["fs", "imap", "web"])
    def foo(request):
        return request.param

    @pytest_twisted.ensureDeferred{optional_call}
    async def test_succeed(foo):
        await defer.succeed(foo)
        if foo == "web":
            raise RuntimeError("baz")
    """.format(optional_call=empty_optional_call)
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 2, "failed": 1})


def test_twisted_greenlet(testdir, cmd_opts):
    test_file = """
    import pytest, greenlet

    MAIN = None

    @pytest.fixture(scope="session", autouse=True)
    def set_MAIN(request, twisted_greenlet):
        global MAIN
        MAIN = twisted_greenlet

    def test_MAIN():
        assert MAIN is not None
        assert MAIN is greenlet.getcurrent()
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 1})


def test_blockon_in_fixture(testdir, cmd_opts):
    test_file = """
    from twisted.internet import reactor, defer
    import pytest
    import pytest_twisted

    @pytest.fixture(scope="module", params=["fs", "imap", "web"])
    def foo(request):
        d1, d2 = defer.Deferred(), defer.Deferred()
        reactor.callLater(0.01, d1.callback, 1)
        reactor.callLater(0.02, d2.callback, request.param)
        pytest_twisted.blockon(d1)
        return d2

    @pytest_twisted.inlineCallbacks
    def test_succeed(foo):
        x = yield foo
        if x == "web":
            raise RuntimeError("baz")
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 2, "failed": 1})


@skip_if_no_async_await()
def test_blockon_in_fixture_async(testdir, cmd_opts):
    test_file = """
    from twisted.internet import reactor, defer
    import pytest
    import pytest_twisted

    @pytest.fixture(scope="module", params=["fs", "imap", "web"])
    def foo(request):
        d1, d2 = defer.Deferred(), defer.Deferred()
        reactor.callLater(0.01, d1.callback, 1)
        reactor.callLater(0.02, d2.callback, request.param)
        pytest_twisted.blockon(d1)
        return d2

    @pytest_twisted.ensureDeferred
    async def test_succeed(foo):
        x = await foo
        if x == "web":
            raise RuntimeError("baz")
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 2, "failed": 1})


@skip_if_no_async_await()
def test_async_fixture(testdir, cmd_opts):
    pytest_ini_file = """
    [pytest]
    markers =
        redgreenblue
    """
    testdir.makefile('.ini', pytest=pytest_ini_file)
    test_file = """
    from twisted.internet import reactor, defer
    import pytest
    import pytest_twisted

    @pytest_twisted.async_fixture(
        scope="function",
        params=["fs", "imap", "web"],
    )
    @pytest.mark.redgreenblue
    async def foo(request):
        d1, d2 = defer.Deferred(), defer.Deferred()
        reactor.callLater(0.01, d1.callback, 1)
        reactor.callLater(0.02, d2.callback, request.param)
        await d1
        return d2,

    @pytest_twisted.inlineCallbacks
    def test_succeed_blue(foo):
        x = yield foo[0]
        if x == "web":
            raise RuntimeError("baz")
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 2, "failed": 1})


@skip_if_no_async_await()
def test_async_fixture_no_arguments(testdir, cmd_opts, empty_optional_call):
    test_file = """
    from twisted.internet import reactor, defer
    import pytest
    import pytest_twisted

    @pytest_twisted.async_fixture{optional_call}
    async def scope(request):
        return request.scope

    def test_is_function_scope(scope):
        assert scope == "function"
    """.format(optional_call=empty_optional_call)
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 1})


@skip_if_no_async_generators()
def test_async_yield_fixture_concurrent_teardown(testdir, cmd_opts):
    test_file = """
    from twisted.internet import reactor, defer
    import pytest
    import pytest_twisted


    here = defer.Deferred()
    there = defer.Deferred()

    @pytest_twisted.async_yield_fixture()
    async def this():
        yield 42

        there.callback(None)
        reactor.callLater(5, here.cancel)
        await here

    @pytest_twisted.async_yield_fixture()
    async def that():
        yield 37

        here.callback(None)
        reactor.callLater(5, there.cancel)
        await there

    def test_succeed(this, that):
        pass
    """
    testdir.makepyfile(test_file)
    # TODO: add a timeout, failure just hangs indefinitely for now
    # https://github.com/pytest-dev/pytest/issues/4073
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 1})


@skip_if_no_async_generators()
def test_async_yield_fixture_can_await(testdir, cmd_opts):
    test_file = """
    from twisted.internet import reactor, defer
    import pytest_twisted

    @pytest_twisted.async_yield_fixture()
    async def foo():
        d1, d2 = defer.Deferred(), defer.Deferred()
        reactor.callLater(0.01, d1.callback, 1)
        reactor.callLater(0.02, d2.callback, 2)
        await d1

        # Twisted doesn't allow calling back with a Deferred as a value.
        # This deferred is being wrapped up in a tuple to sneak through.
        # https://github.com/twisted/twisted/blob/c0f1394c7bfb04d97c725a353a1f678fa6a1c602/src/twisted/internet/defer.py#L459
        yield d2,

    @pytest_twisted.ensureDeferred
    async def test(foo):
        x = await foo[0]
        assert x == 2
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 1})


@skip_if_no_async_generators()
def test_async_yield_fixture_failed_test(testdir, cmd_opts):
    test_file = """
    import pytest_twisted

    @pytest_twisted.async_yield_fixture()
    async def foo():
        yield 92

    @pytest_twisted.ensureDeferred
    async def test(foo):
        assert False
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    rr.stdout.fnmatch_lines(lines2=["E*assert False"])
    assert_outcomes(rr, {"failed": 1})


@skip_if_no_async_generators()
def test_async_yield_fixture_test_exception(testdir, cmd_opts):
    test_file = """
    import pytest_twisted

    class UniqueLocalException(Exception):
        pass

    @pytest_twisted.async_yield_fixture()
    async def foo():
        yield 92

    @pytest_twisted.ensureDeferred
    async def test(foo):
        raise UniqueLocalException("some message")
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    rr.stdout.fnmatch_lines(lines2=["E*.UniqueLocalException: some message*"])
    assert_outcomes(rr, {"failed": 1})


@skip_if_no_async_generators()
def test_async_yield_fixture_yields_twice(testdir, cmd_opts):
    test_file = """
    import pytest_twisted

    @pytest_twisted.async_yield_fixture()
    async def foo():
        yield 92
        yield 36

    @pytest_twisted.ensureDeferred
    async def test(foo):
        assert foo == 92
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 1, "errors": 1})


@skip_if_no_async_generators()
def test_async_yield_fixture_teardown_exception(testdir, cmd_opts):
    test_file = """
    from twisted.internet import reactor, defer
    import pytest
    import pytest_twisted

    class UniqueLocalException(Exception):
        pass

    @pytest_twisted.async_yield_fixture()
    async def foo(request):
        yield 13

        raise UniqueLocalException("some message")

    @pytest_twisted.ensureDeferred
    async def test_succeed(foo):
        assert foo == 13
    """

    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    rr.stdout.fnmatch_lines(lines2=["E*.UniqueLocalException: some message*"])
    assert_outcomes(rr, {"passed": 1, "errors": 1})


@skip_if_no_async_generators()
def test_async_yield_fixture_no_arguments(
        testdir,
        cmd_opts,
        empty_optional_call,
):
    test_file = """
    from twisted.internet import reactor, defer
    import pytest
    import pytest_twisted

    @pytest_twisted.async_yield_fixture{optional_call}
    async def scope(request):
        yield request.scope

    def test_is_function_scope(scope):
        assert scope == "function"
    """.format(optional_call=empty_optional_call)
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 1})


@skip_if_no_async_generators()
def test_async_yield_fixture_function_scope(testdir, cmd_opts):
    test_file = """
    from twisted.internet import reactor, defer
    import pytest
    import pytest_twisted

    check_me = 0

    @pytest_twisted.async_yield_fixture(scope="function")
    async def foo():
        global check_me

        if check_me != 0:
            raise Exception('check_me already modified before fixture run')

        check_me = 1

        yield 42

        if check_me != 2:
            raise Exception(
                'check_me not updated properly: {}'.format(check_me),
            )

        check_me = 0

    def test_first(foo):
        global check_me

        assert check_me == 1
        assert foo == 42

        check_me = 2

    def test_second(foo):
        global check_me

        assert check_me == 1
        assert foo == 42

        check_me = 2
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 2})


@skip_if_no_async_await()
def test_async_simple_fixture_in_fixture(testdir, cmd_opts):
    test_file = """
    import itertools
    from twisted.internet import reactor, defer
    import pytest
    import pytest_twisted

    @pytest_twisted.async_fixture(name='four')
    async def fixture_four():
        return 4

    @pytest_twisted.async_fixture(name='doublefour')
    async def fixture_doublefour(four):
        return 2 * four

    @pytest_twisted.ensureDeferred
    async def test_four(four):
        assert four == 4

    @pytest_twisted.ensureDeferred
    async def test_doublefour(doublefour):
        assert doublefour == 8
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 2})


@skip_if_no_async_generators()
def test_async_yield_simple_fixture_in_fixture(testdir, cmd_opts):
    test_file = """
    import itertools
    from twisted.internet import reactor, defer
    import pytest
    import pytest_twisted

    @pytest_twisted.async_yield_fixture(name='four')
    async def fixture_four():
        yield 4

    @pytest_twisted.async_yield_fixture(name='doublefour')
    async def fixture_doublefour(four):
        yield 2 * four

    @pytest_twisted.ensureDeferred
    async def test_four(four):
        assert four == 4

    @pytest_twisted.ensureDeferred
    async def test_doublefour(doublefour):
        assert doublefour == 8
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 2})


@skip_if_no_async_await()
@pytest.mark.parametrize('innerasync', [
    pytest.param(truth, id='innerasync={}'.format(truth))
    for truth in [True, False]
])
def test_async_fixture_in_fixture(testdir, cmd_opts, innerasync):
    maybe_async = 'async ' if innerasync else ''
    maybe_await = 'await ' if innerasync else ''
    test_file = """
    import itertools
    from twisted.internet import reactor, defer
    import pytest
    import pytest_twisted

    @pytest_twisted.async_fixture(name='increment')
    async def fixture_increment():
        counts = itertools.count()
        {maybe_async}def increment():
            return next(counts)

        return increment

    @pytest_twisted.async_fixture(name='doubleincrement')
    async def fixture_doubleincrement(increment):
        {maybe_async}def doubleincrement():
            n = {maybe_await}increment()
            return n * 2

        return doubleincrement

    @pytest_twisted.ensureDeferred
    async def test_increment(increment):
        first = {maybe_await}increment()
        second = {maybe_await}increment()
        assert (first, second) == (0, 1)

    @pytest_twisted.ensureDeferred
    async def test_doubleincrement(doubleincrement):
        first = {maybe_await}doubleincrement()
        second = {maybe_await}doubleincrement()
        assert (first, second) == (0, 2)
    """.format(maybe_async=maybe_async, maybe_await=maybe_await)
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 2})
    # assert_outcomes(rr, {"passed": 1})


@skip_if_no_async_generators()
@pytest.mark.parametrize('innerasync', [
    pytest.param(truth, id='innerasync={}'.format(truth))
    for truth in [True, False]
])
def test_async_yield_fixture_in_fixture(testdir, cmd_opts, innerasync):
    maybe_async = 'async ' if innerasync else ''
    maybe_await = 'await ' if innerasync else ''
    test_file = """
    import itertools
    from twisted.internet import reactor, defer
    import pytest
    import pytest_twisted

    @pytest_twisted.async_yield_fixture(name='increment')
    async def fixture_increment():
        counts = itertools.count()
        {maybe_async}def increment():
            return next(counts)

        yield increment

    @pytest_twisted.async_yield_fixture(name='doubleincrement')
    async def fixture_doubleincrement(increment):
        {maybe_async}def doubleincrement():
            n = {maybe_await}increment()
            return n * 2

        yield doubleincrement

    @pytest_twisted.ensureDeferred
    async def test_increment(increment):
        first = {maybe_await}increment()
        second = {maybe_await}increment()
        assert (first, second) == (0, 1)

    @pytest_twisted.ensureDeferred
    async def test_doubleincrement(doubleincrement):
        first = {maybe_await}doubleincrement()
        second = {maybe_await}doubleincrement()
        assert (first, second) == (0, 2)
    """.format(maybe_async=maybe_async, maybe_await=maybe_await)
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 2})


def test_blockon_in_hook(testdir, cmd_opts, request):
    skip_if_reactor_not(request, "default")
    conftest_file = """
    import pytest_twisted
    from twisted.internet import reactor, defer

    def pytest_configure(config):
        pytest_twisted.init_default_reactor()
        d1, d2 = defer.Deferred(), defer.Deferred()
        reactor.callLater(0.01, d1.callback, 1)
        reactor.callLater(0.02, d2.callback, 1)
        pytest_twisted.blockon(d1)
        pytest_twisted.blockon(d2)
    """
    testdir.makeconftest(conftest_file)
    test_file = """
    from twisted.internet import reactor, defer

    def test_succeed():
        d = defer.Deferred()
        reactor.callLater(0.01, d.callback, 1)
        return d
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 1})


def test_wrong_reactor(testdir, cmd_opts, request):
    skip_if_reactor_not(request, "default")
    conftest_file = """
    def pytest_addhooks():
        import twisted.internet.reactor
        twisted.internet.reactor = None
    """
    testdir.makeconftest(conftest_file)
    test_file = """
    def test_succeed():
        pass
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert "WrongReactorAlreadyInstalledError" in rr.stderr.str()


def test_blockon_in_hook_with_qt5reactor(testdir, cmd_opts, request):
    skip_if_reactor_not(request, "qt5reactor")
    conftest_file = """
    import pytest_twisted
    import pytestqt
    from twisted.internet import defer

    def pytest_configure(config):
        pytest_twisted.init_qt5_reactor()
        d = defer.Deferred()

        from twisted.internet import reactor

        reactor.callLater(0.01, d.callback, 1)
        pytest_twisted.blockon(d)
    """
    testdir.makeconftest(conftest_file)
    test_file = """
    from twisted.internet import reactor, defer

    def test_succeed():
        d = defer.Deferred()
        reactor.callLater(0.01, d.callback, 1)
        return d
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 1})


def test_wrong_reactor_with_qt5reactor(testdir, cmd_opts, request):
    skip_if_reactor_not(request, "qt5reactor")
    conftest_file = """
    def pytest_addhooks():
        import twisted.internet.default
        twisted.internet.default.install()
    """
    testdir.makeconftest(conftest_file)
    test_file = """
    def test_succeed():
        pass
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert "WrongReactorAlreadyInstalledError" in rr.stderr.str()


def test_pytest_from_reactor_thread(testdir, cmd_opts, request):
    skip_if_reactor_not(request, "default")
    test_file = """
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
    """
    testdir.makepyfile(test_file)
    runner_file = """
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
    """
    testdir.makepyfile(runner=runner_file)
    # check test file is ok in standalone mode:
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 1, "failed": 1})
    # test embedded mode:
    assert testdir.run(sys.executable, "runner.py", timeout=timeout).ret == 0


def test_blockon_in_hook_with_asyncio(testdir, cmd_opts, request):
    skip_if_reactor_not(request, "asyncio")
    conftest_file = """
    import pytest
    import pytest_twisted
    from twisted.internet import defer

    @pytest.hookimpl(tryfirst=True)
    def pytest_configure(config):
        pytest_twisted._use_asyncio_selector_if_required(config=config)

        pytest_twisted.init_asyncio_reactor()
        d = defer.Deferred()

        from twisted.internet import reactor

        reactor.callLater(0.01, d.callback, 1)
        pytest_twisted.blockon(d)
    """
    testdir.makeconftest(conftest_file)
    test_file = """
    from twisted.internet import reactor, defer

    def test_succeed():
        d = defer.Deferred()
        reactor.callLater(0.01, d.callback, 1)
        return d
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 1})


def test_wrong_reactor_with_asyncio(testdir, cmd_opts, request):
    skip_if_reactor_not(request, "asyncio")
    conftest_file = """
    import pytest
    import pytest_twisted


    @pytest.hookimpl(tryfirst=True)
    def pytest_configure(config):
        pytest_twisted._use_asyncio_selector_if_required(config=config)

    def pytest_addhooks():
        import twisted.internet.default
        twisted.internet.default.install()
    """
    testdir.makeconftest(conftest_file)
    test_file = """
    def test_succeed():
        pass
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert "WrongReactorAlreadyInstalledError" in rr.stderr.str()


@skip_if_no_async_generators()
def test_async_fixture_module_scope(testdir, cmd_opts):
    test_file = """
    from twisted.internet import reactor, defer
    import pytest
    import pytest_twisted

    check_me = 0

    @pytest_twisted.async_yield_fixture(scope="module")
    async def foo():
        global check_me

        if check_me != 0:
            raise Exception('check_me already modified before fixture run')

        check_me = 1

        yield 42

        if check_me != 3:
            raise Exception(
                'check_me not updated properly: {}'.format(check_me),
            )

        check_me = 0

    def test_first(foo):
        global check_me

        assert check_me == 1
        assert foo == 42

        check_me = 2

    def test_second(foo):
        global check_me

        assert check_me == 2
        assert foo == 42

        check_me = 3
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 2})


def test_inlinecallbacks_method_with_fixture_gets_self(testdir, cmd_opts):
    test_file = """
    import pytest
    import pytest_twisted
    from twisted.internet import defer

    @pytest.fixture
    def foo():
        return 37

    class TestClass:
        @pytest_twisted.inlineCallbacks
        def test_self_isinstance(self, foo):
            d = defer.succeed(None)
            yield d
            assert isinstance(self, TestClass)
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts)
    assert_outcomes(rr, {"passed": 1})


def test_inlinecallbacks_method_with_fixture_gets_fixture(testdir, cmd_opts):
    test_file = """
    import pytest
    import pytest_twisted
    from twisted.internet import defer

    @pytest.fixture
    def foo():
        return 37

    class TestClass:
        @pytest_twisted.inlineCallbacks
        def test_self_isinstance(self, foo):
            d = defer.succeed(None)
            yield d
            assert foo == 37
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 1})


@skip_if_no_async_await()
def test_ensuredeferred_method_with_fixture_gets_self(testdir, cmd_opts):
    test_file = """
    import pytest
    import pytest_twisted

    @pytest.fixture
    def foo():
        return 37

    class TestClass:
        @pytest_twisted.ensureDeferred
        async def test_self_isinstance(self, foo):
            assert isinstance(self, TestClass)
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 1})


@skip_if_no_async_await()
def test_ensuredeferred_method_with_fixture_gets_fixture(testdir, cmd_opts):
    test_file = """
    import pytest
    import pytest_twisted

    @pytest.fixture
    def foo():
        return 37

    class TestClass:
        @pytest_twisted.ensureDeferred
        async def test_self_isinstance(self, foo):
            assert foo == 37
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 1})


def test_import_pytest_twisted_in_conftest_py_not_a_problem(testdir, cmd_opts):
    conftest_file = """
    import pytest
    import pytest_twisted


    @pytest.hookimpl(tryfirst=True)
    def pytest_configure(config):
        pytest_twisted._use_asyncio_selector_if_required(config=config)
    """
    testdir.makeconftest(conftest_file)
    test_file = """
    import pytest_twisted

    def test_succeed():
        pass
    """
    testdir.makepyfile(test_file)
    rr = testdir.run(*cmd_opts, timeout=timeout)
    assert_outcomes(rr, {"passed": 1})
