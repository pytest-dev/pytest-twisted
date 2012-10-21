def pytest_configure(config):
    from pytest_twisted import plugin
    config.pluginmanager.register(plugin)


class _loader_plugin(object):

    def pytest_addoption(self, parser):
        group = parser.getgroup("twisted", "run tests for a twisted application")
        group.addoption("--twisted", action="store_true",
                        help="run tests with the twisted reactor")
        # group.addoption('--reactor', help="reactor to use", default=None)
        parser.addini("twisted", "run tests with the twisted reactor")
        # parser.addini("reactor", "reactor to use")

    def pytest_configure(self, config):
        enable = config.getvalue("twisted") or config.getini("twisted") in ("yes", "true", "on", "1")
        if enable:
            pytest_configure(config)

_loader = _loader_plugin()
