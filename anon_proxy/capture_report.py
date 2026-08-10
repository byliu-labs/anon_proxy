"""Summarize PII-free detector metadata from sensitive capture files."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path


def iter_entities(path: str | Path) -> Iterator[dict]:
    with Path(path).open(encoding="utf-8") as capture:
        for line in capture:
            if not line.strip():
                continue
            record = json.loads(line)
            calls = record.get("timing_ms", {}).get("detector_calls", [])
            for call in calls:
                yield from call.get("entities", [])


def _bucket(score: float) -> str:
    lower = min(int(score * 20) / 20, 0.95)
    return f"{lower:.2f}-{lower + 0.05:.2f}"


def summarize(entities: Iterable[dict]) -> dict:
    scores_by_label: dict[str, list[float]] = defaultdict(list)
    by_source: Counter[str] = Counter()
    canary_hits = 0
    for entity in entities:
        scores_by_label[entity["label"]].append(float(entity["score"]))
        by_source[entity["source"]] += 1
        canary_hits += entity["source"] == "canary"

    return {
        "labels": {
            label: _label_summary(scores)
            for label, scores in sorted(scores_by_label.items())
        },
        "by_source": dict(by_source),
        "canary_hits": canary_hits,
    }


def _label_summary(scores: list[float]) -> dict:
    histogram = Counter(_bucket(score) for score in scores)
    return {
        "count": len(scores),
        "min_score": min(scores),
        "p50_score": statistics.median(scores),
        "histogram": dict(sorted(histogram.items())),
    }


def _print_table(summary: dict) -> None:
    print(f"{'label':<16}{'count':>7}{'min':>7}{'p50':>7}  histogram")
    for label, data in summary["labels"].items():
        histogram = "  ".join(
            f"{bucket}:{count}" for bucket, count in data["histogram"].items()
        )
        print(
            f"{label:<16}{data['count']:>7}{data['min_score']:>7.2f}"
            f"{data['p50_score']:>7.2f}  {histogram}"
        )
    print(f"\nby source: {summary['by_source']}")
    print(f"canary hits: {summary['canary_hits']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="anon-proxy-capture-report",
        description="Per-label detection score report from a --capture file.",
    )
    parser.add_argument("capture_file")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args(argv)
    try:
        summary = summarize(iter_entities(args.capture_file))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"error: cannot read {args.capture_file}: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        _print_table(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
