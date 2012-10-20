import sys, greenlet
from twisted.internet import reactor, defer
from twisted.python import failure, log

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


def pytest_configure(config):
    global gr_twisted
    gr_twisted = greenlet.greenlet(_reactor_run)
    gr_twisted.switch()


def _reactor_run():
    print "starting twisted reactor"
    reactor.callLater(0.0, lambda: greenlet.getcurrent().parent.switch())
    reactor.run()
    print "twisted reactor stopped"



def pytest_pyfunc_call(pyfuncitem):
    testfunction = pyfuncitem.obj

    if pyfuncitem._isyieldedfunction():
        res = defer.maybeDeferred(testfunction, *pyfuncitem._args)
    else:
        funcargs = pyfuncitem.funcargs
        testargs = {}
        for arg in pyfuncitem._fixtureinfo.argnames:
            testargs[arg] = funcargs[arg]
        res = defer.maybeDeferred(testfunction, **testargs)
    blockon(res)
    return True


def pytest_unconfigure(config):
    reactor.stop()
    gr_twisted.switch()
