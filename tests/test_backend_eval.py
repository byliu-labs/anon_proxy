from __future__ import annotations

import pytest

from anon_proxy.backend_eval import (
    BenchmarkResult,
    check_parity,
    missing_reference_entities,
)
from anon_proxy.privacy_filter import PIIEntity


class FakeFilter:
    def __init__(self, responses):
        self._responses = responses

    def detect(self, text: str):
        return list(self._responses.get(text, []))


def entity(label: str, text: str, start: int, end: int) -> PIIEntity:
    return PIIEntity(label=label, text=text, start=start, end=end, score=1.0)


def test_missing_reference_entities_normalizes_labels():
    reference = [entity("private_person", "Alice", 0, 5)]
    candidate = [entity("PERSON", "Alice", 0, 5)]

    assert missing_reference_entities(reference, candidate) == ()


def test_missing_reference_entities_reports_any_torch_miss():
    reference = [
        entity("private_person", "Alice", 0, 5),
        entity("private_email", "a@example.com", 10, 23),
    ]
    candidate = [entity("private_person", "Alice", 0, 5)]

    missing = missing_reference_entities(reference, candidate)

    assert len(missing) == 1
    assert missing[0].label == "EMAIL"
    assert missing[0].text == "a@example.com"


def test_covering_candidate_span_is_not_a_miss():
    reference = [
        entity("PERSON", "Alice", 0, 5),
        entity("PERSON", "Smith", 6, 11),
    ]
    candidate = [entity("PERSON", "Alice Smith", 0, 11)]

    assert missing_reference_entities(reference, candidate) == ()


def test_check_parity_passes_when_candidate_has_reference_entities():
    text = "Alice and Bob"
    reference = FakeFilter({text: [entity("PERSON", "Alice", 0, 5)]})
    candidate = FakeFilter(
        {
            text: [
                entity("PERSON", "Alice", 0, 5),
                entity("PERSON", "Bob", 10, 13),
            ]
        }
    )

    [result] = check_parity(reference, candidate, [text])

    assert result.passed is True


def test_check_parity_fails_when_candidate_misses_reference_entity():
    text = "Alice"
    reference = FakeFilter({text: [entity("PERSON", "Alice", 0, 5)]})
    candidate = FakeFilter({text: []})

    [result] = check_parity(reference, candidate, [text])

    assert result.passed is False
    assert result.missing[0].text == "Alice"


@pytest.mark.parametrize(
    ("reference", "candidate", "expected"),
    [
        (10.0, 7.0, 0.3),
        (10.0, 10.0, 0.0),
        (10.0, 12.0, -0.2),
    ],
)
def test_benchmark_speedup(reference, candidate, expected):
    result = BenchmarkResult(reference_median_s=reference, candidate_median_s=candidate)

    assert result.speedup == pytest.approx(expected)
