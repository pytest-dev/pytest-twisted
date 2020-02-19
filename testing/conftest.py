import pytest
import pytest_twisted


pytest_plugins = "_pytest.pytester"


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    pytest_twisted._use_asyncio_selector_if_required(config=config)
