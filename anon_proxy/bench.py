from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from anon_proxy.adapters import anthropic as anthropic_adapter
from anon_proxy.masker import Masker
from anon_proxy.privacy_filter import PrivacyFilter


N_TURNS = 12
PROSE = (
    "We reviewed the deployment pipeline and the rollout looks stable. "
    "Latency percentiles held under the agreed budget through the canary "
    "window, and the error rate stayed flat across all regions. "
)
CODE = (
    "def rollout(stage, replicas):\n"
    "    for r in range(replicas):\n"
    "        client.patch(f'/deploy/{stage}/{r}', json={'weight': r / replicas})\n"
    "    return client.get(f'/deploy/{stage}/status').json()\n"
)


def user_text(i: int) -> str:
    pii = (
        f" Contact Alice Smith at alice.smith@example.com or 555-867-5309 "
        f"about incident {i}."
        if i % 3 == 0
        else ""
    )
    return f"Turn {i}: " + PROSE * 6 + CODE * 4 + pii


def request_body(n: int) -> dict:
    messages: list[dict] = []
    for i in range(n + 1):
        messages.append({"role": "user", "content": user_text(i)})
        if i < n:
            messages.append(
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": f"Reply {i}: " + PROSE * 3}],
                }
            )
    return {"model": "claude-x", "messages": messages}


def percentile(values: list[float], pct: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if pct == 50:
        return float(statistics.median(ordered))
    index = min(len(ordered) - 1, max(0, math.ceil((pct / 100) * len(ordered)) - 1))
    return float(ordered[index])


def summarize_times(times_ms: list[float]) -> dict:
    warm = times_ms[1:] if len(times_ms) > 1 else times_ms
    return {
        "cold_ms": times_ms[0] if times_ms else 0.0,
        "warm_median_ms": percentile(warm, 50),
        "warm_p95_ms": percentile(warm, 95),
        "p50_ms": percentile(times_ms, 50),
        "p90_ms": percentile(times_ms, 90),
        "p99_ms": percentile(times_ms, 99),
        "total_ms": sum(times_ms),
    }


def baseline_failures(current: dict, baseline: dict, ratio: float) -> list[str]:
    baseline_by_name = {arm["name"]: arm for arm in baseline.get("arms", [])}
    failures: list[str] = []
    for arm in current.get("arms", []):
        baseline_arm = baseline_by_name.get(arm["name"])
        if baseline_arm is None:
            continue
        current_ms = float(arm["summary"]["warm_median_ms"])
        baseline_ms = float(baseline_arm["summary"]["warm_median_ms"])
        if baseline_ms <= 0:
            continue
        actual_ratio = current_ms / baseline_ms
        if actual_ratio > ratio:
            failures.append(
                f"{arm['name']} warm_median_ms {current_ms:.3f}ms exceeds "
                f"baseline {baseline_ms:.3f}ms by {actual_ratio:.3f}x"
            )
    return failures


def run_synthetic(*, backends: list[str], turns: int) -> dict:
    arms = []
    for backend in backends:
        masker = Masker(filter=PrivacyFilter(backend=backend))
        times = []
        for i in range(turns):
            body = request_body(i)
            start = time.perf_counter()
            masked = anthropic_adapter.mask_request(body, masker)
            times.append((time.perf_counter() - start) * 1000)
            if "alice.smith@example.com" in str(masked):
                raise RuntimeError("PII leaked through mask during benchmark")
        arms.append(
            {
                "name": backend,
                "backend": backend,
                "turns": turns,
                "summary": summarize_times(times),
                "times_ms": times,
                "store_entries": len(masker.store),
            }
        )
    return {"command": "synthetic", "arms": arms}


def run_replay(
    *, capture: str | Path, backend: str, limit: int | None, unmask: bool
) -> dict:
    records = load_capture(capture, limit)
    masker = Masker(filter=PrivacyFilter(backend=backend))
    mask_times = []
    unmask_times = []
    for record in records:
        body = record["request"]["pre_mask"]
        start = time.perf_counter()
        anthropic_adapter.mask_request(body, masker)
        mask_times.append((time.perf_counter() - start) * 1000)
        if unmask:
            response = record.get("response", {}).get("pre_unmask")
            if isinstance(response, dict):
                start = time.perf_counter()
                anthropic_adapter.unmask_response(response, masker)
                unmask_times.append((time.perf_counter() - start) * 1000)
    arm = {
        "name": backend,
        "backend": backend,
        "records": len(records),
        "summary": summarize_times(mask_times),
        "times_ms": mask_times,
        "store_entries": len(masker.store),
    }
    if unmask:
        arm["unmask_summary"] = summarize_times(unmask_times)
    return {"command": "replay", "capture": str(capture), "arms": [arm]}


def load_capture(path: str | Path, limit: int | None) -> list[dict[str, Any]]:
    records = []
    with Path(path).open(encoding="utf-8") as capture:
        for line in capture:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("provider") != "anthropic":
                continue
            if record.get("path") != "/v1/messages":
                continue
            if not isinstance(record.get("request", {}).get("pre_mask"), dict):
                continue
            records.append(record)
            if limit is not None and len(records) >= limit:
                break
    return records


def _apply_baseline(
    report: dict, baseline_path: str | None, ratio: float | None
) -> int:
    if not baseline_path or ratio is None:
        return 0
    with Path(baseline_path).open(encoding="utf-8") as f:
        baseline = json.load(f)
    failures = baseline_failures(report, baseline, ratio=ratio)
    for failure in failures:
        print(failure, file=sys.stderr)
    return 1 if failures else 0


def _print_report(report: dict) -> None:
    for arm in report["arms"]:
        summary = arm["summary"]
        print(
            f"{arm['name']}: cold={summary['cold_ms']:8.1f}ms "
            f"warm_median={summary['warm_median_ms']:8.1f}ms "
            f"warm_p95={summary['warm_p95_ms']:8.1f}ms "
            f"total={summary['total_ms']:9.1f}ms "
            f"store={arm['store_entries']} entries"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="anon-proxy-bench",
        description="Benchmark anon_proxy masking latency.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    synthetic = subparsers.add_parser("synthetic")
    synthetic.add_argument("--backend", action="append", dest="backends")
    synthetic.add_argument("--turns", type=int, default=N_TURNS)
    synthetic.add_argument("--json", action="store_true")
    synthetic.add_argument("--baseline")
    synthetic.add_argument("--fail-under-ratio", type=float)

    replay = subparsers.add_parser("replay")
    replay.add_argument("--capture", default="capture.jsonl")
    replay.add_argument("--backend", default="auto")
    replay.add_argument("--limit", type=int)
    replay.add_argument("--unmask", action="store_true")
    replay.add_argument("--json", action="store_true")
    replay.add_argument("--baseline")
    replay.add_argument("--fail-under-ratio", type=float)

    args = parser.parse_args(argv)
    try:
        if args.command == "synthetic":
            report = run_synthetic(backends=args.backends or ["auto"], turns=args.turns)
        else:
            report = run_replay(
                capture=args.capture,
                backend=args.backend,
                limit=args.limit,
                unmask=args.unmask,
            )
        failed = _apply_baseline(report, args.baseline, args.fail_under_ratio)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_report(report)
    return failed


if __name__ == "__main__":
    raise SystemExit(main())
