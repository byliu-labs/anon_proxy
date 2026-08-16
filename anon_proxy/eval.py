from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol, TypedDict

from anon_proxy.mapping import normalize_label
from anon_proxy.privacy_filter import PIIEntity, PrivacyFilter


@dataclass(frozen=True)
class LabeledSpan:
    start: int
    end: int
    label: str

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError("span start must be >= 0")
        if self.end <= self.start:
            raise ValueError("span end must be greater than start")
        object.__setattr__(self, "label", normalize_label(self.label))


@dataclass(frozen=True)
class CorpusExample:
    id: str
    text: str
    spans: list[LabeledSpan]


class ScoreInput(TypedDict):
    text: str
    gold: list[LabeledSpan]
    predicted: list[LabeledSpan]


class Detector(Protocol):
    def detect(self, text: str) -> list[PIIEntity]: ...


def load_corpus(path: str | Path) -> list[CorpusExample]:
    examples: list[CorpusExample] = []
    with Path(path).open(encoding="utf-8") as corpus:
        for line_number, line in enumerate(corpus, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            examples.append(_load_example(row, line_number))
    return examples


def evaluate(examples: Iterable[CorpusExample], detector: Detector) -> dict:
    scored = []
    for example in examples:
        scored.append(
            {
                "text": example.text,
                "gold": example.spans,
                "predicted": [
                    _entity_to_span(entity) for entity in detector.detect(example.text)
                ],
            }
        )
    return aggregate(scored)


def aggregate(examples: Iterable[ScoreInput]) -> dict:
    counts: dict[str, dict[str, int]] = {}
    leaked_chars = 0
    gold_chars = 0
    for example in examples:
        gold = example["gold"]
        predicted = example["predicted"]
        labels = {span.label for span in gold} | {span.label for span in predicted}
        for label in labels:
            label_gold = [span for span in gold if span.label == label]
            label_predicted = [span for span in predicted if span.label == label]
            matched = _count_relaxed_matches(label_predicted, label_gold)
            exact = _count_exact_matches(label_predicted, label_gold)
            bucket = counts.setdefault(
                label, {"tp": 0, "fp": 0, "fn": 0, "exact_tp": 0, "support": 0}
            )
            bucket["tp"] += matched
            bucket["fp"] += len(label_predicted) - matched
            bucket["fn"] += len(label_gold) - matched
            bucket["exact_tp"] += exact
            bucket["support"] += len(label_gold)
        leaked, total = _char_leaks(gold, predicted)
        leaked_chars += leaked
        gold_chars += total

    per_label = {label: _metrics(bucket) for label, bucket in sorted(counts.items())}
    overall_counts = {
        "tp": sum(bucket["tp"] for bucket in counts.values()),
        "fp": sum(bucket["fp"] for bucket in counts.values()),
        "fn": sum(bucket["fn"] for bucket in counts.values()),
        "exact_tp": sum(bucket["exact_tp"] for bucket in counts.values()),
        "support": sum(bucket["support"] for bucket in counts.values()),
    }
    return {
        "per_label": per_label,
        "overall": _metrics(overall_counts),
        "char_leak_rate": leaked_chars / gold_chars if gold_chars else 0.0,
        "gold_chars": gold_chars,
        "leaked_chars": leaked_chars,
    }


def _metrics(counts: dict[str, int]) -> dict:
    precision = _divide(counts["tp"], counts["tp"] + counts["fp"])
    recall = _divide(counts["tp"], counts["tp"] + counts["fn"])
    exact_precision = _divide(counts["exact_tp"], counts["tp"] + counts["fp"])
    exact_recall = _divide(counts["exact_tp"], counts["support"])
    return {
        "precision": precision,
        "recall": recall,
        "f1": _divide(2 * precision * recall, precision + recall),
        "exact_f1": _divide(
            2 * exact_precision * exact_recall, exact_precision + exact_recall
        ),
        "support": counts["support"],
    }


def _load_example(row: object, line_number: int) -> CorpusExample:
    if not isinstance(row, dict):
        raise ValueError(f"line {line_number}: expected object")
    example_id = row.get("id")
    text = row.get("text")
    spans = row.get("spans")
    if not isinstance(example_id, str) or not example_id:
        raise ValueError(f"line {line_number}: id must be a non-empty string")
    if not isinstance(text, str):
        raise ValueError(f"line {line_number}: text must be a string")
    if not isinstance(spans, list):
        raise ValueError(f"line {line_number}: spans must be a list")
    parsed_spans = [
        _load_span(span, line_number=line_number, index=index, text=text)
        for index, span in enumerate(spans)
    ]
    return CorpusExample(id=example_id, text=text, spans=parsed_spans)


def _load_span(row: object, *, line_number: int, index: int, text: str) -> LabeledSpan:
    if not isinstance(row, dict):
        raise ValueError(f"line {line_number}: span {index} must be an object")
    try:
        span = LabeledSpan(
            start=row["start"],
            end=row["end"],
            label=row["label"],
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"line {line_number}: span {index}: {error}") from error
    if span.end > len(text):
        raise ValueError(
            f"line {line_number}: span {index} exceeds text length "
            f"({span.end} > {len(text)})"
        )
    if not text[span.start : span.end]:
        raise ValueError(f"line {line_number}: span {index} selects empty text")
    return span


def _entity_to_span(entity: PIIEntity) -> LabeledSpan:
    return LabeledSpan(start=entity.start, end=entity.end, label=entity.label)


def _count_relaxed_matches(
    predicted: list[LabeledSpan], gold: list[LabeledSpan]
) -> int:
    used_gold: set[int] = set()
    matches = 0
    for pred in predicted:
        for index, target in enumerate(gold):
            if index in used_gold:
                continue
            if _overlaps(pred, target):
                used_gold.add(index)
                matches += 1
                break
    return matches


def _count_exact_matches(predicted: list[LabeledSpan], gold: list[LabeledSpan]) -> int:
    used_gold: set[int] = set()
    matches = 0
    for pred in predicted:
        for index, target in enumerate(gold):
            if index in used_gold:
                continue
            if pred.start == target.start and pred.end == target.end:
                used_gold.add(index)
                matches += 1
                break
    return matches


def _char_leaks(
    gold: list[LabeledSpan], predicted: list[LabeledSpan]
) -> tuple[int, int]:
    gold_chars = set()
    covered = set()
    predicted_chars = set()
    for span in predicted:
        predicted_chars.update(range(span.start, span.end))
    for span in gold:
        chars = set(range(span.start, span.end))
        gold_chars.update(chars)
        covered.update(chars & predicted_chars)
    return len(gold_chars - covered), len(gold_chars)


def _overlaps(left: LabeledSpan, right: LabeledSpan) -> bool:
    return left.start < right.end and right.start < left.end


def _divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _parse_recall_floors(value: str | None) -> dict[str, float]:
    if not value:
        return {}
    floors: dict[str, float] = {}
    for item in value.split(","):
        if not item:
            continue
        try:
            label, floor = item.split("=", 1)
            floors[normalize_label(label)] = float(floor)
        except ValueError as error:
            raise ValueError(
                "--fail-under-recall must be comma-separated LABEL=FLOAT entries"
            ) from error
    return floors


def _floor_failures(report: dict, floors: dict[str, float]) -> list[str]:
    failures: list[str] = []
    for label, floor in floors.items():
        recall = report["per_label"].get(label, {"recall": 0.0})["recall"]
        if recall < floor:
            failures.append(f"{label} recall {recall:.3f} below floor {floor:.3f}")
    return failures


def _print_table(report: dict) -> None:
    print(f"{'label':<16}{'p':>7}{'r':>7}{'f1':>7}{'exact':>8}{'n':>6}")
    for label, metrics in report["per_label"].items():
        print(
            f"{label:<16}"
            f"{metrics['precision']:>7.3f}"
            f"{metrics['recall']:>7.3f}"
            f"{metrics['f1']:>7.3f}"
            f"{metrics['exact_f1']:>8.3f}"
            f"{metrics['support']:>6}"
        )
    print(f"\nchar leak rate: {report['char_leak_rate']:.6f}")
    print(f"leaked chars: {report['leaked_chars']} / {report['gold_chars']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="anon-proxy-eval",
        description="Score PII detection precision/recall against a labeled JSONL corpus.",
    )
    parser.add_argument("corpus_file")
    parser.add_argument("--backend", default="auto")
    parser.add_argument("--chunk-size", type=int, default=6000)
    parser.add_argument("--json", action="store_true", help="Emit JSON report.")
    parser.add_argument(
        "--fail-under-recall",
        help="Comma-separated label recall floors, for example PERSON=0.9,EMAIL=0.95.",
    )
    args = parser.parse_args(argv)

    try:
        floors = _parse_recall_floors(args.fail_under_recall)
        examples = load_corpus(args.corpus_file)
        detector = PrivacyFilter(backend=args.backend, chunk_size=args.chunk_size)
        report = evaluate(examples, detector)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_table(report)

    failures = _floor_failures(report, floors)
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
