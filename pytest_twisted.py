import decorator
import greenlet
import pytest

from twisted.internet import defer, reactor
from twisted.internet.threads import blockingCallFromThread
from twisted.python import failure

gr_twisted = None


def blockon(d):
    if reactor.running:
        return block_from_thread(d)

    return blockon_default(d)


def blockon_default(d):
    current = greenlet.getcurrent()
    assert current is not gr_twisted, \
        "blockon cannot be called from the twisted greenlet"
    result = []

    def cb(r):
        result.append(r)
        if greenlet.getcurrent() is not current:
            current.switch(result)

    d.addCallbacks(cb, cb)
    if not result:
        _result = gr_twisted.switch()
        assert _result is result, "illegal switch in blockon"

    if isinstance(result[0], failure.Failure):
        result[0].raiseException()

    return result[0]


def block_from_thread(d):
    return blockingCallFromThread(reactor, lambda x: x, d)


@decorator.decorator
def inlineCallbacks(fun, *args, **kw):
    return defer.inlineCallbacks(fun)(*args, **kw)


def pytest_namespace():
    return dict(inlineCallbacks=inlineCallbacks,
                blockon=blockon)


def stop_twisted_greenlet():
    if gr_twisted:
        reactor.stop()
        gr_twisted.switch()


def pytest_addhooks(pluginmanager):
    global gr_twisted
    if not gr_twisted and not reactor.running:
        gr_twisted = greenlet.greenlet(reactor.run)
        # give me better tracebacks:
        failure.Failure.cleanFailure = lambda self: None


@pytest.fixture(scope="session", autouse=True)
def twisted_greenlet(request):
    request.addfinalizer(stop_twisted_greenlet)
    return gr_twisted


def _pytest_pyfunc_call(pyfuncitem):
    testfunction = pyfuncitem.obj
    if pyfuncitem._isyieldedfunction():
        return testfunction(*pyfuncitem._args)
    else:
        funcargs = pyfuncitem.funcargs
        if hasattr(pyfuncitem, "_fixtureinfo"):
            testargs = {}
            for arg in pyfuncitem._fixtureinfo.argnames:
                testargs[arg] = funcargs[arg]
        else:
            testargs = funcargs
        return testfunction(**testargs)


def pytest_pyfunc_call(pyfuncitem):
    if gr_twisted is not None:
        if gr_twisted.dead:
            raise RuntimeError("twisted reactor has stopped")

        def in_reactor(d, f, *args):
            return defer.maybeDeferred(f, *args).chainDeferred(d)

        d = defer.Deferred()
        reactor.callLater(0.0, in_reactor, d, _pytest_pyfunc_call, pyfuncitem)
        blockon_default(d)
    else:
        if not reactor.running:
            raise RuntimeError("twisted reactor is not running")
        blockingCallFromThread(reactor, _pytest_pyfunc_call, pyfuncitem)
    return True
