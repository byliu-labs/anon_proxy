# Detection-Quality Telemetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the telemetry gaps found in the 2026-07-06 assessment — per-entity label+score records (the evidence that unblocks a `min_score` threshold), session-level aggregate counters (canary hit rate, entities by label/source, cache hit rate), and a structured JSON log option.

**Architecture:** Three additive layers on the existing plumbing. (1) `Masker.mask` already appends per-call records via `telemetry_scope()`, and `--capture` already persists those records as `timing_ms.detector_calls` — we enrich each fresh-detection record with `{label, score, len, source}` per entity (never the raw text). (2) A process-wide thread-safe `MaskerStats` counter object is injected into every `Masker` (including multi-user `make_masker`) and dumped at shutdown. (3) A tiny `EventSink` routes the stderr lines (`[metrics]`, canary warnings, unknown-token warnings, stats dump) through one emitter that has a human format and a `--log-json` JSON-lines format. A `capture-report` CLI turns capture files into per-label score histograms.

**Tech Stack:** stdlib only (`collections.Counter`, `threading`, `json`, `argparse`), pytest.

## Global Constraints

- **No raw PII values in telemetry or stderr** — labels, scores, and lengths only. The `--capture` file is the single place raw PII may land (it already carries the "treat as sensitive" warning and full bodies).
- `uv` only; `uv run pytest tests/ -q`, `uv run ruff check .`, `uv run ruff format --check .` green after every task (the exact CI jobs).
- All new behavior is opt-in or invisible: default stderr output unchanged unless `--log-json` is passed; telemetry records only grow new keys (additive — existing capture consumers keep working).
- No commits to main — branch per PR.
- Base on `land/integration` (or Kevin's main once the stack lands).

---

### Task 1: Per-entity `{label, score, len, source}` in mask telemetry

Today a capture record's `detector_calls` tells you a mask call took 6400ms and missed the cache — but not what was detected or how confident the model was. Plan 13 (score threshold) is blocked on exactly this.

**Files:**
- Modify: `anon_proxy/masker.py` (`Masker.mask`, one new module helper)
- Test: `tests/test_masker.py`

**Interfaces:**
- Produces: fresh-detection mask records gain `"entities": [{"source": "known"|"regex"|"ml"|"canary", "label": str, "score": float, "len": int}, ...]`. Cache-hit records do NOT carry entities (they are re-observations of an already-recorded detection; including them would double-count every history replay and skew histograms).
- Consumes: `telemetry_scope()` (existing), `PIIEntity` (existing).

- [ ] **Step 1: Write the failing test**

```python
class TestEntityTelemetry:
    def _masker(self):
        # FakeFilter pattern already used across tests/test_masker.py: an
        # object with .detect(text) returning canned PIIEntity lists.
        fake = FakeFilter(
            [PIIEntity(label="PERSON", text="Alice", start=11, end=16, score=0.97)]
        )
        return Masker(filter=fake, canary="off", min_known_entity_len=0)

    def test_fresh_mask_records_entities(self):
        m = self._masker()
        with telemetry_scope() as calls:
            m.mask("My name is Alice.")
        rec = next(c for c in calls if c["op"] == "mask")
        assert rec["entities"] == [
            {"source": "ml", "label": "PERSON", "score": 0.97, "len": 5}
        ]
        # privacy: the raw value must never appear in the record
        assert "Alice" not in json.dumps(rec)

    def test_cache_hit_records_no_entities(self):
        m = self._masker()
        m.mask("My name is Alice.")  # fill cache
        with telemetry_scope() as calls:
            m.mask("My name is Alice.")
        rec = next(c for c in calls if c["op"] == "mask")
        assert rec["cache_hit"] is True
        assert "entities" not in rec
```

- [ ] **Step 2: Run, verify fail** — `uv run pytest tests/test_masker.py::TestEntityTelemetry -v` → FAIL (`KeyError: 'entities'`).

- [ ] **Step 3: Implement.** Module helper in `masker.py`:

```python
def _entity_summary(entities: list[PIIEntity], source: str) -> list[dict]:
    """Label/score/length only — never the matched text (keeps raw PII out
    of telemetry records and anything downstream of them)."""
    return [
        {
            "source": source,
            "label": e.label,
            "score": round(e.score, 4),
            "len": e.end - e.start,
        }
        for e in entities
    ]
```

In `Masker.mask`, the final fresh-path telemetry append becomes:

```python
        if record is not None:
            record.append(
                {
                    "op": "mask",
                    "chars": len(text),
                    "ms": (time.perf_counter() - t0) * 1000,
                    "cache_hit": False,
                    "entities": (
                        _entity_summary(known_entities, "known")
                        + _entity_summary(regex_entities, "regex")
                        + _entity_summary(ml_entities, "ml")
                        + _entity_summary(canary_hits, "canary")
                    ),
                }
            )
```

(`canary_hits` is already in scope at that point; no other call sites change. Capture picks this up for free — `detector_calls` is these records verbatim.)

- [ ] **Step 4: Run tests + lint/format** → green.

- [ ] **Step 5: Commit**

```bash
git add anon_proxy/masker.py tests/test_masker.py
git commit -m "feat: per-entity label/score/len/source in mask telemetry records

Flows into --capture detector_calls unchanged. Raw matched text is
deliberately excluded - telemetry carries no PII values."
```

---

### Task 2: `anon-proxy-capture-report` — score histograms from capture files

Task 1's data is only *observable* through this tool, so Tasks 1+2 ship as one PR. This is the instrument that produces the `min_score` evidence.

**Files:**
- Create: `anon_proxy/capture_report.py`
- Modify: `pyproject.toml` (`[project.scripts]`)
- Test: `tests/test_capture_report.py`

**Interfaces:**
- Consumes: capture JSONL records with `timing_ms.detector_calls[].entities` (Task 1 shape).
- Produces: console script `anon-proxy-capture-report <capture.jsonl>`; functions `iter_entities(path) -> Iterator[dict]`, `summarize(entities: Iterable[dict]) -> dict`, `main(argv=None) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
import json

from anon_proxy.capture_report import iter_entities, main, summarize


def _record(entities):
    return {
        "ts": "2026-07-06T00:00:00+00:00",
        "timing_ms": {"detector_calls": [{"op": "mask", "entities": entities}]},
    }


def _write(tmp_path, records):
    p = tmp_path / "cap.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in records))
    return p


ENTS = [
    {"source": "ml", "label": "PERSON", "score": 0.97, "len": 11},
    {"source": "ml", "label": "PERSON", "score": 0.62, "len": 4},
    {"source": "regex", "label": "SSN", "score": 1.0, "len": 11},
    {"source": "canary", "label": "PHONE", "score": 1.0, "len": 12},
]


def test_iter_entities_walks_all_records(tmp_path):
    p = _write(tmp_path, [_record(ENTS[:2]), _record(ENTS[2:])])
    assert list(iter_entities(p)) == ENTS


def test_iter_entities_skips_pre_task1_records(tmp_path):
    """Old capture files have detector_calls without 'entities' — no crash."""
    p = _write(tmp_path, [_record(ENTS[:1]), {"timing_ms": {"detector_calls": [{"op": "mask"}]}}])
    assert list(iter_entities(p)) == ENTS[:1]


def test_summarize_per_label_stats():
    s = summarize(ENTS)
    person = s["labels"]["PERSON"]
    assert person["count"] == 2
    assert person["min_score"] == 0.62
    assert person["p50_score"] == pytest.approx(0.795)
    assert sum(person["histogram"].values()) == 2  # buckets "0.60-0.65" etc.
    assert s["canary_hits"] == 1
    assert s["by_source"] == {"ml": 2, "regex": 1, "canary": 1}


def test_main_prints_table(tmp_path, capsys):
    p = _write(tmp_path, [_record(ENTS)])
    assert main([str(p)]) == 0
    out = capsys.readouterr().out
    assert "PERSON" in out and "0.62" in out and "canary" in out


def test_main_missing_file(capsys):
    assert main(["/nonexistent/cap.jsonl"]) == 1
    assert "error" in capsys.readouterr().err
```

- [ ] **Step 2: Run, verify fail** (module doesn't exist).

- [ ] **Step 3: Implement `anon_proxy/capture_report.py`**

```python
"""Summarize detection-quality telemetry from a --capture JSONL file.

Reads the per-entity {label, score, len, source} records that Masker puts
in each capture record's timing_ms.detector_calls and prints per-label
score distributions. This is the evidence tool for choosing a min_score
threshold: run real traffic with --capture, then inspect where genuine
entities' scores bottom out.

Only labels/scores/lengths are read; this tool never prints captured text.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Iterator


def iter_entities(path: str | Path) -> Iterator[dict]:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            record = json.loads(line)
            for call in record.get("timing_ms", {}).get("detector_calls", []):
                yield from call.get("entities", [])


def _bucket(score: float) -> str:
    lo = min(int(score * 20) / 20, 0.95)
    return f"{lo:.2f}-{lo + 0.05:.2f}"


def summarize(entities: Iterable[dict]) -> dict:
    by_label: dict[str, list[float]] = defaultdict(list)
    by_source: Counter = Counter()
    canary_hits = 0
    for e in entities:
        by_label[e["label"]].append(e["score"])
        by_source[e["source"]] += 1
        if e["source"] == "canary":
            canary_hits += 1
    labels = {}
    for label, scores in sorted(by_label.items()):
        hist: Counter = Counter(_bucket(s) for s in scores)
        labels[label] = {
            "count": len(scores),
            "min_score": min(scores),
            "p50_score": statistics.median(scores),
            "histogram": dict(sorted(hist.items())),
        }
    return {
        "labels": labels,
        "by_source": dict(by_source),
        "canary_hits": canary_hits,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="anon-proxy-capture-report",
        description="Per-label detection score report from a --capture file.",
    )
    parser.add_argument("capture_file")
    parser.add_argument("--json", action="store_true", help="emit JSON, not a table")
    args = parser.parse_args(argv)
    try:
        summary = summarize(iter_entities(args.capture_file))
    except OSError as e:
        print(f"error: cannot read {args.capture_file}: {e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(summary, indent=2))
        return 0
    print(f"{'label':<16}{'count':>7}{'min':>7}{'p50':>7}  histogram")
    for label, s in summary["labels"].items():
        hist = "  ".join(f"{b}:{n}" for b, n in s["histogram"].items())
        print(
            f"{label:<16}{s['count']:>7}{s['min_score']:>7.2f}"
            f"{s['p50_score']:>7.2f}  {hist}"
        )
    print(f"\nby source: {summary['by_source']}")
    print(f"canary hits (survived masking, caught by canary): {summary['canary_hits']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

pyproject:

```toml
[project.scripts]
anon-proxy = "anon_proxy.server:main"
anon-proxy-store = "anon_proxy.store_cli:main"
anon-proxy-capture-report = "anon_proxy.capture_report:main"
```

- [ ] **Step 4: Run tests + lint/format** → green. Then one live smoke: run the proxy with `--capture /tmp/cap.jsonl` against the mock-upstream E2E harness (or a short `test_mask.py` session), then `uv run anon-proxy-capture-report /tmp/cap.jsonl` and eyeball the table. Delete the capture file after (`mv` to trash if unsure — it contains raw PII).

- [ ] **Step 5: Commit**

```bash
git add anon_proxy/capture_report.py tests/test_capture_report.py pyproject.toml
git commit -m "feat: anon-proxy-capture-report - per-label score histograms

Turns --capture files into the min_score evidence: per-label count,
min/p50 score, 0.05-wide histogram buckets, source breakdown, canary
hit count. Reads only labels/scores/lengths, never captured text."
```

---

### Task 3: Session aggregates — `MaskerStats`

Answers "over this whole session, what was the cache hit rate, how many canary saves, how many unknown tokens?" without grepping stderr. One process-wide object, shared across all maskers (crucially: also the multi-user registry's).

**Files:**
- Create: `anon_proxy/stats.py`
- Modify: `anon_proxy/masker.py` (accept + feed `stats`), `anon_proxy/server.py` (create, inject into both single-user `Masker(...)` and `make_masker`, dump at shutdown)
- Test: `tests/test_stats.py`, additions to `tests/test_server.py`

**Interfaces:**
- Produces: `MaskerStats` with `record_mask(cache_hit: bool, entities: list[dict] | None = None)`, `record_unknown_tokens(n: int)`, `snapshot() -> dict`. `Masker.__init__` gains `stats: MaskerStats | None = None`. Server dumps `[stats] {...json...}` to stderr at lifespan shutdown.
- Consumes: Task 1's `_entity_summary` output shape for per-label counting.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_stats.py
from concurrent.futures import ThreadPoolExecutor

from anon_proxy.stats import MaskerStats


def test_snapshot_counts():
    s = MaskerStats()
    s.record_mask(cache_hit=True)
    s.record_mask(
        cache_hit=False,
        entities=[
            {"source": "ml", "label": "PERSON", "score": 0.9, "len": 5},
            {"source": "canary", "label": "PHONE", "score": 1.0, "len": 12},
        ],
    )
    s.record_unknown_tokens(2)
    snap = s.snapshot()
    assert snap["mask_calls"] == 2
    assert snap["mask_cache_hits"] == 1
    assert snap["entities"]["ml/PERSON"] == 1
    assert snap["canary_hits"] == 1
    assert snap["unknown_tokens"] == 2


def test_thread_safety():
    s = MaskerStats()
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda _: s.record_mask(cache_hit=False), range(2000)))
    assert s.snapshot()["mask_calls"] == 2000
```

And in `tests/test_masker.py`:

```python
def test_masker_feeds_stats():
    stats = MaskerStats()
    fake = FakeFilter(
        [PIIEntity(label="PERSON", text="Alice", start=11, end=16, score=0.97)]
    )
    m = Masker(filter=fake, canary="off", min_known_entity_len=0, stats=stats)
    m.mask("My name is Alice.")
    m.mask("My name is Alice.")  # cache hit
    snap = stats.snapshot()
    assert snap["mask_calls"] == 2
    assert snap["mask_cache_hits"] == 1
    assert snap["entities"]["ml/PERSON"] == 1
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement `anon_proxy/stats.py`**

```python
"""Process-wide detection counters, aggregated across all maskers.

One instance per server process, shared by every Masker (including all
per-client maskers in multi-user mode). Counts only — no text, no scores
per entity (per-entity detail lives in --capture records)."""

from __future__ import annotations

import threading
from collections import Counter


class MaskerStats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._mask_calls = 0
        self._mask_cache_hits = 0
        self._entities: Counter = Counter()  # "source/LABEL" -> count
        self._canary_hits = 0
        self._unknown_tokens = 0

    def record_mask(
        self, *, cache_hit: bool, entities: list[dict] | None = None
    ) -> None:
        with self._lock:
            self._mask_calls += 1
            if cache_hit:
                self._mask_cache_hits += 1
            for e in entities or ():
                self._entities[f"{e['source']}/{e['label']}"] += 1
                if e["source"] == "canary":
                    self._canary_hits += 1

    def record_unknown_tokens(self, n: int) -> None:
        if not n:
            return
        with self._lock:
            self._unknown_tokens += n

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "mask_calls": self._mask_calls,
                "mask_cache_hits": self._mask_cache_hits,
                "entities": dict(self._entities),
                "canary_hits": self._canary_hits,
                "unknown_tokens": self._unknown_tokens,
            }
```

Masker wiring: `__init__` stores `self._stats = stats`; in `mask()` call `self._stats.record_mask(cache_hit=..., entities=...)` at the same two points the telemetry record is appended (reuse the `_entity_summary` result — build it once, feed both); in `_sub()` call `self._stats.record_unknown_tokens(len(unknown))`. All calls guarded by `if self._stats is not None`.

Server wiring: create `stats = MaskerStats()` in `main()`, pass `stats=stats` in the single-user `Masker(...)` call AND inside `make_masker` (this is the exact half-wiring trap that bit `make_masker` before — grep for every `Masker(` construction in server.py and wire ALL of them). In `create_app`'s lifespan `finally` block (next to `capture.close()`):

```python
            print(f"[stats] {json.dumps(app.state.stats.snapshot())}", file=sys.stderr)
```

with `app.state.stats = stats` threaded through like `app.state.metrics`.

- [ ] **Step 4: Integration test** in `tests/test_server.py` — use the existing ASGITransport fixture pattern: run one masked request through the app, exit the lifespan, assert stderr (capfd) contains `[stats] ` and that parsing the JSON after it gives `mask_calls >= 1`.

- [ ] **Step 5: Run full suite + lint/format** → green.

- [ ] **Step 6: Commit**

```bash
git add anon_proxy/stats.py anon_proxy/masker.py anon_proxy/server.py tests/
git commit -m "feat: process-wide MaskerStats with shutdown dump

Cache hit rate, entities by source/label, canary hits, unknown tokens -
aggregated across all maskers including multi-user registry clients,
printed as one [stats] JSON line at shutdown."
```

---

### Task 4: `--log-json` structured logs

**Files:**
- Create: `anon_proxy/events.py`
- Modify: `anon_proxy/server.py` (`_log_metrics`, stats dump, flag), `anon_proxy/masker.py` (canary + unknown-token warnings route through an injectable sink)
- Test: `tests/test_events.py`, additions to `tests/test_server.py`

**Interfaces:**
- Produces: `EventSink(json_mode: bool)` with `emit(event: str, human: str, **fields)`; module default `SINK = EventSink(json_mode=False)` and `set_json_mode(on: bool)`. JSON mode writes `{"event": ..., **fields}` one-per-line to stderr; human mode writes `human` exactly as today (byte-identical default output).
- Consumes: Tasks 1–3 (their stderr lines are the ones being routed).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_events.py
import json

from anon_proxy.events import EventSink


def test_human_mode_prints_human_line(capsys):
    EventSink(json_mode=False).emit("metrics", "e2e=5ms", e2e_ms=5.0)
    assert capsys.readouterr().err == "e2e=5ms\n"


def test_json_mode_prints_json_line(capsys):
    EventSink(json_mode=True).emit("metrics", "e2e=5ms", e2e_ms=5.0)
    line = capsys.readouterr().err
    assert json.loads(line) == {"event": "metrics", "e2e_ms": 5.0}
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement `anon_proxy/events.py`**

```python
"""One funnel for operational stderr output, with a JSON-lines mode.

Human mode preserves today's exact log lines. JSON mode replaces each with
one machine-parseable object per line ({"event": ..., **fields}) so k8s
log pipelines can ingest metrics, canary warnings and unknown-token
warnings without regex scraping. Fields must never contain raw PII."""

from __future__ import annotations

import json
import sys


class EventSink:
    def __init__(self, json_mode: bool = False) -> None:
        self.json_mode = json_mode

    def emit(self, event: str, human: str, **fields) -> None:
        if self.json_mode:
            print(json.dumps({"event": event, **fields}), file=sys.stderr)
        else:
            print(human, file=sys.stderr)
        sys.stderr.flush()


SINK = EventSink()


def set_json_mode(on: bool) -> None:
    SINK.json_mode = on
```

- [ ] **Step 4: Route the four producers through `SINK.emit`, preserving today's human strings exactly:**
  - `server._log_metrics` → `SINK.emit("metrics", <current formatted line>, provider=..., e2e_ms=..., upstream_ms=..., proxy_ms=..., tokens=usage)`
  - stats dump (Task 3) → `SINK.emit("stats", f"[stats] {payload}", **snapshot)`
  - `Masker` canary warning → `SINK.emit("canary", <current warning line>, label=hit.label, len=len(hit.text), action=self._canary)` — **drop `hit.text` from the JSON fields** (human line keeps it, as today; JSON is what lands in log aggregation, so it must carry no raw PII)
  - `Masker` unknown-token warning → `SINK.emit("unmask_unknown_token", <current line>, token=token)`

  In `masker.py` import the module-level `SINK` (no constructor change needed — the sink is process-global like the mode flag).

- [ ] **Step 5: Add the flag** in `server.py`:

```python
    parser.add_argument(
        "--log-json",
        action="store_true",
        default=os.environ.get("ANON_PROXY_LOG_JSON", "") == "1",
        help="Emit metrics/warnings as JSON lines on stderr (for log pipelines).",
    )
```

and `events.set_json_mode(args.log_json)` in `main()`. Integration test: run a masked request through the ASGI app with json mode on; every non-banner stderr line must `json.loads` cleanly; with it off, output matches the pre-task snapshot.

- [ ] **Step 6: Run full suite + lint/format** → green.

- [ ] **Step 7: Commit**

```bash
git add anon_proxy/events.py anon_proxy/masker.py anon_proxy/server.py tests/
git commit -m "feat: --log-json structured stderr events

Metrics, stats, canary and unknown-token warnings route through one
EventSink. Human output is byte-identical by default; JSON mode emits
one object per line and carries labels/lengths only, never PII values."
```

---

## PR decomposition

| PR | Tasks | Deliverable a reviewer can observe |
|----|-------|-----------------------------------|
| 1 | 1+2 | Run traffic with `--capture`, then `anon-proxy-capture-report cap.jsonl` prints per-label score histograms — the min_score evidence pipeline end-to-end |
| 2 | 3 | `[stats]` JSON line at shutdown with cache hit rate / canary hits / entity counts |
| 3 | 4 | `--log-json` turns all operational stderr into parseable JSON lines |

Task 1 without Task 2 is a commit, not a PR (its data is invisible without the report tool) — they ship together. PRs 2 and 3 are independent of each other; both depend on PR 1 only for the entity-shape reuse (PR 2) and line inventory (PR 3), so land in order 1 → 2 → 3.

## What this unblocks

- **Plan 13 (min_score threshold):** capture a week of real traffic → `anon-proxy-capture-report` shows where true-positive scores bottom out per label → pick thresholds with evidence instead of guessing.
- **Canary hit rate as a masking-quality KPI:** `snapshot()["canary_hits"] / snapshot()["mask_calls"]` — if the regex canary keeps catching what the ML pass missed, that's the signal to tune merge gaps or patterns.
- **k8s observability:** `--log-json` makes the multi-user deployment's logs ingestible without scraping ANSI-colored human lines.
