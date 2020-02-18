import sys

import pytest


pytest_plugins = "_pytest.pytester"


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    if (
            config.getoption("reactor") == 'asyncio'
            and sys.platform == 'win32'
            and sys.version_info >= (3, 8)
    ):
        # https://twistedmatrix.com/trac/ticket/9766
        import asyncio

        selector_policy = asyncio.WindowsSelectorEventLoopPolicy()
        asyncio.set_event_loop_policy(selector_policy)
