from __future__ import annotations

import statistics
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from anon_proxy.mapping import normalize_label
from anon_proxy.privacy_filter import PIIEntity, PrivacyFilter


DEFAULT_EVAL_TEXTS = [
    "Alice Smith called from 555-867-5309 about bob@example.com.",
    "Send the contract to 123 Main St., Apt #4 before Jan 1, 2027.",
    "Dr. Jean-Luc O'Neil met ACME Corp in San Francisco.",
]


@dataclass(frozen=True)
class EntitySignature:
    label: str
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class ParityResult:
    text: str
    reference: tuple[EntitySignature, ...]
    candidate: tuple[EntitySignature, ...]
    missing: tuple[EntitySignature, ...]

    @property
    def passed(self) -> bool:
        return not self.missing


@dataclass(frozen=True)
class BenchmarkResult:
    reference_median_s: float
    candidate_median_s: float

    @property
    def speedup(self) -> float:
        if self.reference_median_s <= 0:
            return 0.0
        return 1.0 - (self.candidate_median_s / self.reference_median_s)


def signature(entity: PIIEntity) -> EntitySignature:
    return EntitySignature(
        label=normalize_label(entity.label),
        text=entity.text,
        start=entity.start,
        end=entity.end,
    )


def missing_reference_entities(
    reference: Sequence[PIIEntity],
    candidate: Sequence[PIIEntity],
) -> tuple[EntitySignature, ...]:
    candidate_signatures = tuple(signature(entity) for entity in candidate)
    missing: list[EntitySignature] = []
    for reference_entity in reference:
        reference_signature = signature(reference_entity)
        if not any(
            _covers(reference_signature, candidate_signature)
            for candidate_signature in candidate_signatures
        ):
            missing.append(reference_signature)
    return tuple(missing)


def _covers(reference: EntitySignature, candidate: EntitySignature) -> bool:
    return (
        candidate.label == reference.label
        and candidate.start <= reference.start
        and candidate.end >= reference.end
    )


def check_parity(
    reference_filter: PrivacyFilter,
    candidate_filter: PrivacyFilter,
    texts: Sequence[str] = DEFAULT_EVAL_TEXTS,
) -> list[ParityResult]:
    results: list[ParityResult] = []
    for text in texts:
        reference = reference_filter.detect(text)
        candidate = candidate_filter.detect(text)
        results.append(
            ParityResult(
                text=text,
                reference=tuple(signature(entity) for entity in reference),
                candidate=tuple(signature(entity) for entity in candidate),
                missing=missing_reference_entities(reference, candidate),
            )
        )
    return results


def benchmark_filter(
    detector: Callable[[str], list[PIIEntity]],
    texts: Sequence[str] = DEFAULT_EVAL_TEXTS,
    *,
    warmups: int = 1,
    iterations: int = 5,
) -> float:
    for _ in range(warmups):
        for text in texts:
            detector(text)

    timings: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        for text in texts:
            detector(text)
        timings.append(time.perf_counter() - start)
    return statistics.median(timings)


def compare_backends(
    reference_filter: PrivacyFilter,
    candidate_filter: PrivacyFilter,
    texts: Sequence[str] = DEFAULT_EVAL_TEXTS,
    *,
    warmups: int = 1,
    iterations: int = 5,
) -> BenchmarkResult:
    return BenchmarkResult(
        reference_median_s=benchmark_filter(
            reference_filter.detect,
            texts,
            warmups=warmups,
            iterations=iterations,
        ),
        candidate_median_s=benchmark_filter(
            candidate_filter.detect,
            texts,
            warmups=warmups,
            iterations=iterations,
        ),
    )
