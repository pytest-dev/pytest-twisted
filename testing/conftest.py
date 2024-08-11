import pytest
import pytest_twisted.core


pytest_plugins = "pytester"


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    pytest_twisted.core._use_asyncio_selector_if_required(config=config)
