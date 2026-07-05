from __future__ import annotations

import pytest

from anon_proxy.masker import Masker
from anon_proxy.mapping import PIIStore
from anon_proxy.privacy_filter import PIIEntity


class FakeFilter:
    def __init__(self) -> None:
        self._entities_by_text: dict[str, list[PIIEntity]] = {}

    def set(self, text: str, entities: list[PIIEntity]) -> None:
        self._entities_by_text[text] = entities

    def detect(self, text: str) -> list[PIIEntity]:
        return list(self._entities_by_text.get(text, []))


def span(
    label: str,
    start: int,
    end: int,
    *,
    text: str,
    score: float = 1.0,
) -> PIIEntity:
    return PIIEntity(
        label=label,
        text=text[start:end],
        start=start,
        end=end,
        score=score,
    )


@pytest.fixture
def fake_filter() -> FakeFilter:
    return FakeFilter()


@pytest.fixture
def store() -> PIIStore:
    return PIIStore()


@pytest.fixture
def make_masker(fake_filter: FakeFilter, store: PIIStore):
    def factory(**kwargs) -> Masker:
        return Masker(filter=fake_filter, store=store, **kwargs)

    return factory
