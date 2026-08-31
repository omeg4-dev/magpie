import pytest

from magpie.store import Store


class Clock:
    """A hand-cranked clock, so tests can say when things happened."""

    def __init__(self, now_ms: int = 1_700_000_000_000) -> None:
        self.now = now_ms

    def __call__(self) -> int:
        return self.now

    def advance(self, ms: int) -> int:
        self.now += ms
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    return Store(tmp_path / "store", clock=clock)


#: The smallest real PNG there is: one transparent pixel. Enough for anything
#: that only needs the bytes to be an image.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4949484452000000010000000108060000001f15c489"
    "0000000a49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082")


@pytest.fixture
def png():
    return PNG
