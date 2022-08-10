from pytest_twisted import ensureDeferred
from hypothesis import given
from hypothesis.strategies import integers


async def test(x):
    assert isinstance(x, int)

original_test = test
test = ensureDeferred(test)
test = given(x=integers())(test)
