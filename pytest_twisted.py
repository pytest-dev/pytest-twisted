import functools
import inspect
import warnings

import decorator
import greenlet
import pytest

from twisted.internet import error, defer
from twisted.internet.threads import blockingCallFromThread
from twisted.python import failure


class WrongReactorAlreadyInstalledError(Exception):
    pass


class UnrecognizedCoroutineMarkError(Exception):
    @classmethod
    def from_mark(cls, mark):
        return cls(
            'Coroutine wrapper mark not recognized: {}'.format(repr(mark)),
        )


class AsyncGeneratorFixtureDidNotStopError(Exception):
    @classmethod
    def from_generator(cls, generator):
        return cls(
            'async fixture did not stop: {}'.format(generator),
        )


class AsyncFixtureUnsupportedScopeError(Exception):
    @classmethod
    def from_scope(cls, scope):
        return cls(
            'Unsupported scope used for async fixture: {}'.format(scope)
        )


class _config:
    external_reactor = False


class _instances:
    gr_twisted = None
    reactor = None


def _deprecate(deprecated, recommended):
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            warnings.warn(
                '{deprecated} has been deprecated, use {recommended}'.format(
                    deprecated=deprecated,
                    recommended=recommended,
                ),
                DeprecationWarning,
                stacklevel=2,
            )
            return f(*args, **kwargs)

        return wrapper

    return decorator


def blockon(d):
    if _config.external_reactor:
        return block_from_thread(d)

    return blockon_default(d)


def blockon_default(d):
    current = greenlet.getcurrent()
    assert (
        current is not _instances.gr_twisted
    ), "blockon cannot be called from the twisted greenlet"
    result = []

    def cb(r):
        result.append(r)
        if greenlet.getcurrent() is not current:
            current.switch(result)

    d.addCallbacks(cb, cb)
    if not result:
        _result = _instances.gr_twisted.switch()
        assert _result is result, "illegal switch in blockon"

    if isinstance(result[0], failure.Failure):
        result[0].raiseException()

    return result[0]


def block_from_thread(d):
    return blockingCallFromThread(_instances.reactor, lambda x: x, d)


@decorator.decorator
def inlineCallbacks(fun, *args, **kw):
    return defer.inlineCallbacks(fun)(*args, **kw)


@decorator.decorator
def ensureDeferred(fun, *args, **kw):
    return defer.ensureDeferred(fun(*args, **kw))


def init_twisted_greenlet():
    if _instances.reactor is None or _instances.gr_twisted:
        return

    if not _instances.reactor.running:
        _instances.gr_twisted = greenlet.greenlet(_instances.reactor.run)
        # give me better tracebacks:
        failure.Failure.cleanFailure = lambda self: None
    else:
        _config.external_reactor = True


def stop_twisted_greenlet():
    if _instances.gr_twisted:
        _instances.reactor.stop()
        _instances.gr_twisted.switch()


class _CoroutineWrapper:
    def __init__(self, coroutine, mark):
        self.coroutine = coroutine
        self.mark = mark


def _marked_async_fixture(mark):
    @functools.wraps(pytest.fixture)
    def fixture(*args, **kwargs):
        try:
            scope = args[0]
        except IndexError:
            scope = kwargs.get('scope', 'function')

        if scope != 'function':
            raise AsyncFixtureUnsupportedScopeError.from_scope(scope=scope)

        def marker(f):
            @functools.wraps(f)
            def w(*args, **kwargs):
                return _CoroutineWrapper(
                    coroutine=f(*args, **kwargs),
                    mark=mark,
                )

            return w

        def decorator(f):
            result = pytest.fixture(*args, **kwargs)(marker(f))

            return result

        return decorator

    return fixture


async_fixture = _marked_async_fixture('async_fixture')
async_yield_fixture = _marked_async_fixture('async_yield_fixture')


@defer.inlineCallbacks
def _pytest_pyfunc_call(pyfuncitem):
    testfunction = pyfuncitem.obj
    async_generators = []
    funcargs = pyfuncitem.funcargs
    if hasattr(pyfuncitem, "_fixtureinfo"):
        testargs = {}
        for arg in pyfuncitem._fixtureinfo.argnames:
            if isinstance(funcargs[arg], _CoroutineWrapper):
                wrapper = funcargs[arg]

                if wrapper.mark == 'async_fixture':
                    arg_value = yield defer.ensureDeferred(
                        wrapper.coroutine
                    )
                elif wrapper.mark == 'async_yield_fixture':
                    async_generators.append((arg, wrapper))
                    arg_value = yield defer.ensureDeferred(
                        wrapper.coroutine.__anext__(),
                    )
                else:
                    raise UnrecognizedCoroutineMarkError.from_mark(
                        mark=wrapper.mark,
                    )
            else:
                arg_value = funcargs[arg]

            testargs[arg] = arg_value
    else:
        testargs = funcargs
    result = yield testfunction(**testargs)

    async_generator_deferreds = [
        (arg, defer.ensureDeferred(g.coroutine.__anext__()))
        for arg, g in reversed(async_generators)
    ]

    for arg, d in async_generator_deferreds:
        try:
            yield d
        except StopAsyncIteration:
            continue
        else:
            raise AsyncGeneratorFixtureDidNotStopError.from_generator(
                generator=arg,
            )

    defer.returnValue(result)


def pytest_pyfunc_call(pyfuncitem):
    if _instances.gr_twisted is not None:
        if _instances.gr_twisted.dead:
            raise RuntimeError("twisted reactor has stopped")

        def in_reactor(d, f, *args):
            return defer.maybeDeferred(f, *args).chainDeferred(d)

        d = defer.Deferred()
        _instances.reactor.callLater(
            0.0, in_reactor, d, _pytest_pyfunc_call, pyfuncitem
        )
        blockon_default(d)
    else:
        if not _instances.reactor.running:
            raise RuntimeError("twisted reactor is not running")
        blockingCallFromThread(
            _instances.reactor, _pytest_pyfunc_call, pyfuncitem
        )
    return True


@pytest.fixture(scope="session", autouse=True)
def twisted_greenlet(request):
    request.addfinalizer(stop_twisted_greenlet)
    return _instances.gr_twisted


def init_default_reactor():
    import twisted.internet.default

    module = inspect.getmodule(twisted.internet.default.install)

    module_name = module.__name__.split(".")[-1]
    reactor_type_name, = (x for x in dir(module) if x.lower() == module_name)
    reactor_type = getattr(module, reactor_type_name)

    _install_reactor(
        reactor_installer=twisted.internet.default.install,
        reactor_type=reactor_type,
    )


def init_qt5_reactor():
    import qt5reactor

    _install_reactor(
        reactor_installer=qt5reactor.install, reactor_type=qt5reactor.QtReactor
    )


def init_asyncio_reactor():
    from twisted.internet import asyncioreactor

    _install_reactor(
        reactor_installer=asyncioreactor.install,
        reactor_type=asyncioreactor.AsyncioSelectorReactor,
    )


reactor_installers = {
    "default": init_default_reactor,
    "qt5reactor": init_qt5_reactor,
    "asyncio": init_asyncio_reactor,
}


def _install_reactor(reactor_installer, reactor_type):
    try:
        reactor_installer()
    except error.ReactorAlreadyInstalledError:
        import twisted.internet.reactor

        if not isinstance(twisted.internet.reactor, reactor_type):
            raise WrongReactorAlreadyInstalledError(
                "expected {} but found {}".format(
                    reactor_type, type(twisted.internet.reactor)
                )
            )

    import twisted.internet.reactor

    _instances.reactor = twisted.internet.reactor
    init_twisted_greenlet()


def pytest_addoption(parser):
    group = parser.getgroup("twisted")
    group.addoption(
        "--reactor",
        default="default",
        choices=tuple(reactor_installers.keys()),
    )


def pytest_configure(config):
    pytest.inlineCallbacks = _deprecate(
        deprecated='pytest.inlineCallbacks',
        recommended='pytest_twisted.inlineCallbacks',
    )(inlineCallbacks)
    pytest.blockon = _deprecate(
        deprecated='pytest.blockon',
        recommended='pytest_twisted.blockon',
    )(blockon)

    reactor_installers[config.getoption("reactor")]()
