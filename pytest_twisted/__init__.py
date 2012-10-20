
def pytest_addoption(parser):
    group = parser.getgroup("twisted", "run tests for a twisted application")
    group.addoption("--with-twisted", action="store_true",
                    help="run tests with the twisted reactor")
    group.addoption('--reactor', help="reactor to use", default=None)
    parser.addini("with_twisted", "run tests with the twisted reactor")


def pytest_configure(config):
    enable = config.getvalue("with_twisted") or config.getini("with_twisted") in ("yes", "true", "on", "1")
    if enable:
        from pytest_twisted import plugin
        config.pluginmanager.register(plugin)
