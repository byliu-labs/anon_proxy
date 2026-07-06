from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_BINS = tuple(f"{i / 10:.1f}-{(i + 1) / 10:.1f}" for i in range(10))


def build_report(paths: list[str | Path]) -> dict[str, Any]:
    labels: dict[str, dict[str, Any]] = {}
    files = [str(Path(path)) for path in paths]
    records = 0
    entities = 0
    for path in paths:
        with Path(path).open(encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(f"{path}:{line_no}: invalid JSON: {e}") from e
                records += 1
                for entity in _iter_entities(record):
                    label = str(entity["label"])
                    bucket = labels.setdefault(label, _new_bucket())
                    score = float(entity["score"])
                    length = int(entity["len"])
                    source = str(entity["source"])
                    bucket["count"] += 1
                    bucket["_score_total"] += score
                    bucket["_len_total"] += length
                    bucket["min_score"] = min(bucket["min_score"], score)
                    bucket["max_score"] = max(bucket["max_score"], score)
                    bucket["score_histogram"][_score_bin(score)] += 1
                    bucket["sources"][source] += 1
                    entities += 1
    return {
        "files": files,
        "records": records,
        "entities": entities,
        "labels": {label: _finalize_bucket(bucket) for label, bucket in labels.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="anon-proxy-capture-report",
        description="Summarize safe detector telemetry from anon-proxy capture JSONL.",
    )
    parser.add_argument("captures", nargs="+", help="Capture JSONL files to read.")
    parser.add_argument(
        "--json", action="store_true", help="Emit JSON instead of text."
    )
    args = parser.parse_args(argv)
    try:
        report = build_report([Path(p) for p in args.captures])
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_text_report(report)
    return 0


def _iter_entities(record: dict[str, Any]):
    timing = record.get("timing_ms")
    if not isinstance(timing, dict):
        return
    calls = timing.get("detector_calls")
    if not isinstance(calls, list):
        return
    for call in calls:
        if not isinstance(call, dict) or call.get("op") != "mask":
            continue
        entities = call.get("entities")
        if not isinstance(entities, list):
            continue
        for entity in entities:
            if _valid_entity(entity):
                yield entity


def _valid_entity(entity: Any) -> bool:
    return (
        isinstance(entity, dict)
        and isinstance(entity.get("label"), str)
        and isinstance(entity.get("source"), str)
        and isinstance(entity.get("score"), (int, float))
        and isinstance(entity.get("len"), int)
    )


def _new_bucket() -> dict[str, Any]:
    return {
        "count": 0,
        "_score_total": 0.0,
        "_len_total": 0,
        "min_score": 1.0,
        "max_score": 0.0,
        "score_histogram": Counter({label: 0 for label in _BINS}),
        "sources": Counter(),
    }


def _finalize_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    count = bucket["count"]
    return {
        "count": count,
        "avg_score": round(bucket["_score_total"] / count, 4) if count else 0.0,
        "min_score": round(bucket["min_score"], 4) if count else 0.0,
        "max_score": round(bucket["max_score"], 4) if count else 0.0,
        "avg_len": round(bucket["_len_total"] / count, 2) if count else 0.0,
        "score_histogram": dict(bucket["score_histogram"]),
        "sources": dict(bucket["sources"]),
    }


def _score_bin(score: float) -> str:
    clamped = min(max(score, 0.0), 1.0)
    index = min(int(clamped * 10), 9)
    return _BINS[index]


def _print_text_report(report: dict[str, Any]) -> None:
    print(
        f"capture files: {len(report['files'])}  "
        f"records: {report['records']}  entities: {report['entities']}"
    )
    for label, data in sorted(report["labels"].items()):
        sources = ", ".join(f"{k}={v}" for k, v in sorted(data["sources"].items()))
        print(
            f"\n{label}: count={data['count']} avg_score={data['avg_score']:.4f} "
            f"min={data['min_score']:.4f} max={data['max_score']:.4f} "
            f"avg_len={data['avg_len']:.2f} sources={sources}"
        )
        for bucket, count in data["score_histogram"].items():
            if count:
                print(f"  {bucket}: {count}")


if __name__ == "__main__":
    raise SystemExit(main())
