import functools
import inspect
import sys
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
            'Unsupported scope {0!r} used for async fixture'.format(scope)
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


# def stop_twisted_greenlet():
#     if _instances.gr_twisted:
#         _instances.reactor.stop()
#         _instances.gr_twisted.switch()


class _CoroutineWrapper:
    def __init__(self, coroutine, mark):
        # TODO: really an async def now, maybe, if that worked out
        self.coroutine = coroutine
        self.__name__ = self.coroutine.__name__ + 'ptcr'
        self.mark = mark

    # def __call__(self):
    #     print()


def _marked_async_fixture(mark):
    @functools.wraps(pytest.fixture)
    def fixture(*args, **kwargs):
        try:
            scope = args[0]
        except IndexError:
            scope = kwargs.get('scope', 'function')

        if scope != 'function':
            raise AsyncFixtureUnsupportedScopeError.from_scope(scope=scope)

        # def marker(f):
        #     @functools.wraps(f)
        #     def w(*args, **kwargs):
        #         return _CoroutineWrapper(
        #             coroutine=f(*args, **kwargs),
        #             mark=mark,
        #         )
        #
        #     return w

        def marker(f):
            f._pytest_twisted_coroutine_wrapper = _CoroutineWrapper(
                coroutine=f,
                mark=mark,
            )

            return f

        def decorator(f):
            # result = pytest.fixture(*args, **kwargs)(
            #     _CoroutineWrapper(coroutine=f, mark=mark),
            # )
            result = pytest.fixture(*args, **kwargs)(marker(f))

            return result

        return decorator

    return fixture


async_fixture = _marked_async_fixture('async_fixture')
async_yield_fixture = _marked_async_fixture('async_yield_fixture')


def pytest_fixture_setup(fixturedef, request):
    maybe_wrapper = getattr(
        fixturedef.func,
        '_pytest_twisted_coroutine_wrapper',
        None,
    )
    if not isinstance(maybe_wrapper, _CoroutineWrapper):
        return None

    if _instances.gr_twisted is not None:
        if _instances.gr_twisted.dead:
            raise RuntimeError("twisted reactor has stopped")

        def in_reactor(d, f, *args):
            return defer.maybeDeferred(f, *args).chainDeferred(d)

        d = defer.Deferred()
        _instances.reactor.callLater(
            0.0, in_reactor, d, _pytest_fixture_setup, fixturedef, request, maybe_wrapper
        )
        result = blockon_default(d)
    else:
        if not _instances.reactor.running:
            raise RuntimeError("twisted reactor is not running")
        result = blockingCallFromThread(
            _instances.reactor, _pytest_fixture_setup, fixturedef, request, maybe_wrapper
        )
    # return None
    return result


async_yield_fixture_cache = {}


@defer.inlineCallbacks
def _pytest_fixture_setup(fixturedef, request, wrapper):
    # return None
    #
    # if not isinstance(fixturedef.func, _CoroutineWrapper):
    #     return None

    fixture_function = fixturedef.func

    async_generators = []

    kwargs = {
        name: request.getfixturevalue(name)
        for name in fixturedef.argnames
    }

    if wrapper.mark == 'async_fixture':
        arg_value = yield defer.ensureDeferred(
            fixture_function(**kwargs)
        )
    elif wrapper.mark == 'async_yield_fixture':
        # async_generators.append((arg, wrapper))
        coroutine = fixture_function(**kwargs)
        # TODO: use request.addfinalizer() instead?
        async_yield_fixture_cache[request.param_index] = coroutine
        arg_value = yield defer.ensureDeferred(
            coroutine.__anext__(),
        )
    else:
        raise UnrecognizedCoroutineMarkError.from_mark(
            mark=wrapper.mark,
        )

    fixturedef.cached_result = (arg_value, request.param_index, None)

    defer.returnValue(arg_value)

    # async_generator_deferreds = [
    #     (arg, defer.ensureDeferred(g.coroutine.__anext__()))
    #     for arg, g in reversed(async_generators)
    # ]
    #
    # for arg, d in async_generator_deferreds:
    #     try:
    #         yield d
    #     except StopAsyncIteration:
    #         continue
    #     else:
    #         raise AsyncGeneratorFixtureDidNotStopError.from_generator(
    #             generator=arg,
    #         )


# @defer.inlineCallbacks
# def _pytest_fixture_post_finalizer(fixturedef, request, coroutine):
#     try:
#         yield defer.ensureDeferred(
#             coroutine.__anext__(),
#         )
#     except StopAsyncIteration:
#         # TODO: i don't remember why this makes sense...
#         pass
#     else:
#         raise AsyncGeneratorFixtureDidNotStopError.from_generator(
#             generator=coroutine,
#         )


# TODO: but don't we want to do the finalizer?  not wait until post it?
def pytest_fixture_post_finalizer(fixturedef, request):
    maybe_coroutine = async_yield_fixture_cache.pop(request.param_index, None)

    if maybe_coroutine is None:
        return None

    coroutine = maybe_coroutine

    to_be_torn_down.append(defer.ensureDeferred(coroutine.__anext__()))
    return None

    # try:
    #     if _instances.gr_twisted is not None:
    #         if _instances.gr_twisted.dead:
    #             raise RuntimeError("twisted reactor has stopped")
    #
    #         def in_reactor(d, f, *args):
    #             return defer.maybeDeferred(f, *args).chainDeferred(d)
    #
    #         d = defer.Deferred()
    #         _instances.reactor.callLater(
    #             0.0, in_reactor, d, _pytest_fixture_post_finalizer, fixturedef, request, coroutine
    #         )
    #         result = blockon_default(d)
    #     else:
    #         if not _instances.reactor.running:
    #             raise RuntimeError("twisted reactor is not running")
    #         result = blockingCallFromThread(
    #             _instances.reactor, _pytest_fixture_post_finalizer, fixturedef, request, coroutine
    #         )
    # except StopAsyncIteration as e:
    #     print(e)
    #
    # # async_yield_fixture_cache.pop(request.param_index)
    #
    # # return None
    return result


@defer.inlineCallbacks
def tear_it_down(deferred):
    try:
        yield deferred
    except StopAsyncIteration:
        return
    except Exception as e:
        e = e
    else:
        e = None

    raise AsyncGeneratorFixtureDidNotStopError.from_generator(
        generator=deferred,
    )


to_be_torn_down = []

# TODO: https://docs.pytest.org/en/latest/reference.html#_pytest.hookspec.pytest_runtest_protocol
#       claims it should also take a nextItem but that triggers a direct error


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item):
    yield

    # deferreds = []
    #
    # while len(to_be_torn_down) > 0:
    #     coroutine = to_be_torn_down.pop(0)
    #     deferreds.append(defer.ensureDeferred(coroutine.__anext__()))
    #
    # for deferred in deferreds:
    while len(to_be_torn_down) > 0:
        deferred = to_be_torn_down.pop(0)
        if _instances.gr_twisted is not None:
            if _instances.gr_twisted.dead:
                raise RuntimeError("twisted reactor has stopped")

            def in_reactor(d, f, *args):
                # return f.chainDeferred(d)
                return defer.maybeDeferred(f, *args).chainDeferred(d)

            d = defer.Deferred()
            _instances.reactor.callLater(
                0.0, in_reactor, d, tear_it_down, deferred
            )
            blockon_default(d)
            # blockon_default(tear_it_down(deferred))
        else:
            if not _instances.reactor.running:
                raise RuntimeError("twisted reactor is not running")
            blockingCallFromThread(
                _instances.reactor, tear_it_down, deferred,
            )
            # blockingCallFromThread(
            #     _instances.reactor, tear_it_down, deferred
            # )


@defer.inlineCallbacks
def _pytest_pyfunc_call(pyfuncitem):
    kwargs = {name: value for name, value in pyfuncitem.funcargs.items() if name in pyfuncitem._fixtureinfo.argnames}
    result = yield pyfuncitem.obj(**kwargs)
    defer.returnValue(result)

    return
    # print()
    #
    # testfunction = pyfuncitem.obj
    # async_generators = []
    # funcargs = pyfuncitem.funcargs
    # if hasattr(pyfuncitem, "_fixtureinfo"):
    #     testargs = {}
    #     for arg in pyfuncitem._fixtureinfo.argnames:
    #         if isinstance(funcargs[arg], _CoroutineWrapper):
    #             wrapper = funcargs[arg]
    #
    #             if wrapper.mark == 'async_fixture':
    #                 arg_value = yield defer.ensureDeferred(
    #                     wrapper.coroutine
    #                 )
    #             elif wrapper.mark == 'async_yield_fixture':
    #                 async_generators.append((arg, wrapper))
    #                 arg_value = yield defer.ensureDeferred(
    #                     wrapper.coroutine.__anext__(),
    #                 )
    #             else:
    #                 raise UnrecognizedCoroutineMarkError.from_mark(
    #                     mark=wrapper.mark,
    #                 )
    #         else:
    #             arg_value = funcargs[arg]
    #
    #         testargs[arg] = arg_value
    # else:
    #     testargs = funcargs
    # result = yield testfunction(**testargs)
    #
    # async_generator_deferreds = [
    #     (arg, defer.ensureDeferred(g.coroutine.__anext__()))
    #     for arg, g in reversed(async_generators)
    # ]
    #
    # for arg, d in async_generator_deferreds:
    #     try:
    #         yield d
    #     except StopAsyncIteration:
    #         continue
    #     else:
    #         raise AsyncGeneratorFixtureDidNotStopError.from_generator(
    #             generator=arg,
    #         )
    #
    # defer.returnValue(result)


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


# TODO: switch to some plugin callback to guarantee order before other fixtures?
@pytest.fixture(scope="session", autouse=True)
def twisted_greenlet(request):
    # request.addfinalizer(stop_twisted_greenlet)
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


def pytest_unconfigure(config):
    stop_twisted_greenlet()


def _use_asyncio_selector_if_required(config):
    # https://twistedmatrix.com/trac/ticket/9766
    # https://github.com/pytest-dev/pytest-twisted/issues/80

    if (
        config.getoption("reactor", "default") == "asyncio"
        and sys.platform == 'win32'
        and sys.version_info >= (3, 8)
    ):
        import asyncio

        selector_policy = asyncio.WindowsSelectorEventLoopPolicy()
        asyncio.set_event_loop_policy(selector_policy)
