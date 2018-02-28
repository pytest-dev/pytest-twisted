import sys

import decorator
import greenlet
import pytest

from twisted.internet import error, defer
from twisted.internet.threads import blockingCallFromThread
from twisted.python import failure


class _instances:
    gr_twisted = None
    reactor = None


def pytest_namespace():
    return dict(inlineCallbacks=inlineCallbacks, blockon=blockon)


def blockon(d):
    if _instances.reactor.running:
        return block_from_thread(d)

    return blockon_default(d)


def blockon_default(d):
    current = greenlet.getcurrent()
    assert current is not _instances.gr_twisted, \
        'blockon cannot be called from the twisted greenlet'
    result = []

    def cb(r):
        result.append(r)
        if greenlet.getcurrent() is not current:
            current.switch(result)

    d.addCallbacks(cb, cb)
    if not result:
        _result = _instances.gr_twisted.switch()
        assert _result is result, 'illegal switch in blockon'

    if isinstance(result[0], failure.Failure):
        result[0].raiseException()

    return result[0]


def block_from_thread(d):
    return blockingCallFromThread(_instances.reactor, lambda x: x, d)


@decorator.decorator
def inlineCallbacks(fun, *args, **kw):
    return defer.inlineCallbacks(fun)(*args, **kw)


def init_twisted_greenlet():
    if _instances.reactor is None:
        return

    if not _instances.gr_twisted and not _instances.reactor.running:
        _instances.gr_twisted = greenlet.greenlet(_instances.reactor.run)
        # give me better tracebacks:
        failure.Failure.cleanFailure = lambda self: None


def stop_twisted_greenlet():
    if _instances.gr_twisted:
        _instances.reactor.stop()
        _instances.gr_twisted.switch()


def _pytest_pyfunc_call(pyfuncitem):
    testfunction = pyfuncitem.obj
    if pyfuncitem._isyieldedfunction():
        return testfunction(*pyfuncitem._args)
    else:
        funcargs = pyfuncitem.funcargs
        if hasattr(pyfuncitem, '_fixtureinfo'):
            testargs = {}
            for arg in pyfuncitem._fixtureinfo.argnames:
                testargs[arg] = funcargs[arg]
        else:
            testargs = funcargs
        return testfunction(**testargs)


def pytest_pyfunc_call(pyfuncitem):
    if _instances.gr_twisted is not None:
        if _instances.gr_twisted.dead:
            raise RuntimeError('twisted reactor has stopped')

        def in_reactor(d, f, *args):
            return defer.maybeDeferred(f, *args).chainDeferred(d)

        d = defer.Deferred()
        _instances.reactor.callLater(
            0.0, in_reactor, d, _pytest_pyfunc_call, pyfuncitem
        )
        blockon_default(d)
    else:
        if not _instances.reactor.running:
            raise RuntimeError('twisted reactor is not running')
        blockingCallFromThread(
            _instances.reactor, _pytest_pyfunc_call, pyfuncitem
        )
    return True


@pytest.fixture(scope="session", autouse=True)
def twisted_greenlet(request, reactor):
    request.addfinalizer(stop_twisted_greenlet)
    return _instances.gr_twisted


def init_reactor():
    import twisted.internet.reactor
    _instances.reactor = twisted.internet.reactor
    init_twisted_greenlet()


def init_qt5_reactor(qapp):
    import qt5reactor
    try:
        qt5reactor.install()
    except error.ReactorAlreadyInstalledError:
        if not isinstance(_instances.reactor, qt5reactor.QtReactor):
            stop_twisted_greenlet()
            _instances.gr_twisted = None
            del sys.modules['twisted.internet.reactor']
            qt5reactor.install()
    init_reactor()


def pytest_addoption(parser):
    group = parser.getgroup('twisted')
    group.addoption(
        '--reactor',
        default='default',
        choices=('default', 'qt5reactor'),
    )


def pytest_configure(config):
    reactor_fixture = {
        'default': init_reactor,
        'qt5reactor': init_qt5_reactor,
    }[config.getoption('reactor')]

    class ReactorPlugin(object):
        reactor = staticmethod(
            pytest.fixture(scope='session', autouse=True)(reactor_fixture)
        )

    config.pluginmanager.register(ReactorPlugin())
