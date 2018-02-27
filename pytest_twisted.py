import sys

import decorator
import greenlet
import pytest

from twisted.internet import error, defer, reactor
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
    print('checkpoint', 'pytest-twisted', 'inlineCallbacks')
    return defer.inlineCallbacks(fun)(*args, **kw)


def pytest_namespace():
    return dict(inlineCallbacks=inlineCallbacks,
                blockon=blockon)


def stop_twisted_greenlet():
    if gr_twisted:
        reactor.stop()
        gr_twisted.switch()


def create_twisted_greenlet():
    global gr_twisted
    if not gr_twisted and not reactor.running:
        gr_twisted = greenlet.greenlet(reactor.run)
        # give me better tracebacks:
        failure.Failure.cleanFailure = lambda self: None


def pytest_addhooks(pluginmanager):
    create_twisted_greenlet()


def pytest_addoption(parser):
    group = parser.getgroup('twisted')
    group.addoption('--qt5reactor', dest='qt5reactor', action='store_true',
                    help='prepare for use with qt5reactor')


def pytest_configure(config):
    # TODO: why is the parameter needed?
    def default_reactor():
        print('checkpoint', 'pytest-twisted', 'reactor (default)')
        global reactor
        from twisted.internet import reactor
        create_twisted_greenlet()

    def qt5_reactor(qapp):
        print('checkpoint', 'pytest-twisted', 'reactor (qt5)')
        global gr_twisted
        global reactor
        import qt5reactor

        try:
            qt5reactor.install()
        except error.ReactorAlreadyInstalledError:
            if not isinstance(reactor, qt5reactor.QtReactor):
                stop_twisted_greenlet()
                gr_twisted = None
                del sys.modules['twisted.internet.reactor']
                qt5reactor.install()
                print('checkpoint', 'pytest-twisted', 'qt5reactor installed')
                from twisted.internet import reactor

                create_twisted_greenlet()
        else:
            create_twisted_greenlet()

    if config.getoption('qt5reactor'):
        reactor_fixture = qt5_reactor
    else:
        reactor_fixture = default_reactor

    class ReactorPlugin(object):
        reactor = staticmethod(
            pytest.fixture(scope='session', autouse=True)(reactor_fixture)
        )

    config.pluginmanager.register(ReactorPlugin())


@pytest.fixture(scope="session", autouse=True)
def twisted_greenlet(request, reactor):
    print('checkpoint', 'pytest-twisted', 'twisted_greenlet')
    request.addfinalizer(stop_twisted_greenlet)
    return gr_twisted


def _pytest_pyfunc_call(pyfuncitem):
    print('checkpoint', 'pytest-twisted', '_pytest_pyfunc_call')
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
    print('checkpoint', 'pytest-twisted', 'pytest_pyfunc_call')
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
