import greenlet, pytest
from twisted.internet import reactor, defer
from twisted.python import failure
from decorator import decorator

gr_twisted = None


def blockon(d):
    current = greenlet.getcurrent()
    assert current is not gr_twisted, "blockon cannot be called from the twisted greenlet"
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


@decorator
def inlineCallbacks(fun, *args, **kw):
    return defer.inlineCallbacks(fun)(*args, **kw)


def pytest_namespace():
    return dict(inlineCallbacks=inlineCallbacks)


def stop_twisted_greenlet():
    if gr_twisted:
        reactor.stop()
        gr_twisted.switch()


@pytest.fixture(scope="session", autouse=True)
def twisted_greenlet(request):
    global gr_twisted
    gr_twisted = greenlet.greenlet(reactor.run)
    failure.Failure.cleanFailure = lambda self: None  # give me better tracebacks
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
    if gr_twisted.dead:
        raise RuntimeError("twisted reactor has stopped")

    d = defer.Deferred()
    reactor.callLater(0.0, lambda: defer.maybeDeferred(_pytest_pyfunc_call, pyfuncitem).chainDeferred(d))
    blockon(d)
    return True
