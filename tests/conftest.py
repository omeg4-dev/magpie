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
