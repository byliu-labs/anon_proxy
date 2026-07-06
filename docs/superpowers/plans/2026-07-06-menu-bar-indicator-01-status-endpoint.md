# Status Endpoint & Proxy Metrics — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an in-memory metrics accumulator and an internal `GET /_status` endpoint to the proxy so any observer (the menu-bar dino, a k8s probe, a curl) can see presence, activity, PII counts, per-agent attribution, token throughput, and a masking-error alarm — all counts, never content.

**Architecture:** A thread-safe `ProxyMetrics` object lives on `app.state.metrics`. `_handle_proxy` records one request, its store-delta (unique PII), its client label, and its output tokens; the masking call is wrapped so a masking error increments an alarm counter and fails **closed** (never forwards unmasked). A new `/_status` route (registered before the catch-all provider dispatch) serializes `metrics.snapshot()` plus static facts (listen addr, providers, backend, store size).

**Tech Stack:** Python ≥3.10, Starlette, httpx, pytest. No new runtime dependencies.

## Global Constraints

- Python `>=3.10` — use `X | None` unions, `dict[...]` generics (no `typing.Optional`).
- Use `uv run pytest ...` for all test runs; never call `.venv/bin/*` directly.
- `/_status` and metrics MUST expose only counts/labels — never request content, PII originals, placeholder mappings, or auth headers.
- Metrics recording MUST never break a proxied request: a bug in metrics must not raise out of `_handle_proxy`'s masking/forwarding path (telemetry fails open; masking fails closed).
- The `/_status` route MUST be registered before the `/{path:path}` catch-all, or it is shadowed and treated as provider `_status`.
- No commits to `main`/`master`; this work happens on a feature branch.

---

### Task 1: `ProxyMetrics` accumulator

**Files:**
- Create: `anon_proxy/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: nothing (leaf module; standard library only).
- Produces:
  - `class ProxyMetrics` with fields `started_at: float`, `requests_masked_total: int`, `entities_masked_total: int`, `masking_errors_total: int`, `tokens_out_total: int`, `last_request_at: float | None`, `last_client: str | None`, `by_client: dict[str, dict[str, int]]`.
  - `record_request(client_label: str, entities_masked: int, now: float | None = None) -> None`
  - `record_masking_error(now: float | None = None) -> None`
  - `record_tokens(client_label: str, n: int, now: float | None = None) -> None`
  - `tokens_per_sec(now: float | None = None) -> float`
  - `snapshot(now: float | None = None) -> dict`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_metrics.py
import math

from anon_proxy.metrics import ProxyMetrics


def test_record_request_counts_and_attributes():
    m = ProxyMetrics(started_at=1000.0)
    m.record_request("Claude Code", entities_masked=3, now=1001.0)
    m.record_request("Codex", entities_masked=1, now=1002.0)
    snap = m.snapshot(now=1002.0)
    assert snap["requests_masked_total"] == 2
    assert snap["entities_masked_total"] == 4
    assert snap["last_client"] == "Codex"
    assert snap["last_request_at"] == 1002.0
    assert snap["by_client"]["Claude Code"]["requests"] == 1
    assert snap["by_client"]["Codex"]["requests"] == 1


def test_masking_error_increments_alarm():
    m = ProxyMetrics(started_at=0.0)
    assert m.snapshot(now=0.0)["masking_errors_total"] == 0
    m.record_masking_error()
    m.record_masking_error()
    assert m.snapshot(now=0.0)["masking_errors_total"] == 2


def test_tokens_accumulate_and_attribute():
    m = ProxyMetrics(started_at=0.0)
    m.record_tokens("Claude Code", 100, now=1.0)
    m.record_tokens("Claude Code", 50, now=2.0)
    snap = m.snapshot(now=2.0)
    assert snap["tokens_out_total"] == 150
    assert snap["by_client"]["Claude Code"]["tokens"] == 150


def test_rate_positive_during_burst_and_decays_when_idle():
    m = ProxyMetrics(started_at=0.0)
    # steady 200 tok/s for a few ticks
    for t in (1.0, 1.5, 2.0, 2.5, 3.0):
        m.record_tokens("Claude Code", 100, now=t)
    hot = m.tokens_per_sec(now=3.0)
    assert hot > 50.0  # clearly running
    # long idle -> decays toward zero
    cold = m.tokens_per_sec(now=30.0)
    assert cold < 1.0


def test_zero_or_negative_tokens_ignored():
    m = ProxyMetrics(started_at=0.0)
    m.record_tokens("x", 0, now=1.0)
    m.record_tokens("x", -5, now=1.0)
    assert m.snapshot(now=1.0)["tokens_out_total"] == 0


def test_snapshot_is_json_safe_and_has_no_content_fields():
    import json
    m = ProxyMetrics(started_at=0.0)
    m.record_request("Claude Code", 2, now=1.0)
    snap = m.snapshot(now=1.0)
    json.dumps(snap)  # must not raise
    # only count/label keys — never content
    assert set(snap) == {
        "started_at", "uptime_sec", "requests_masked_total",
        "entities_masked_total", "masking_errors_total", "tokens_out_total",
        "tokens_per_sec", "last_request_at", "last_client", "by_client",
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_metrics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'anon_proxy.metrics'`

- [ ] **Step 3: Write the implementation**

```python
# anon_proxy/metrics.py
"""In-memory, thread-safe proxy activity metrics.

Holds only counts and agent labels — never request content, PII originals, or
placeholder mappings. Serialized by the /_status endpoint for observers such as
the menu-bar indicator and k8s probes.
"""

from __future__ import annotations

import math
import threading
import time

_TAU = 3.0  # EWMA time constant (seconds) for the throughput estimate


class ProxyMetrics:
    def __init__(self, started_at: float | None = None) -> None:
        self.started_at = time.time() if started_at is None else started_at
        self.requests_masked_total = 0
        self.entities_masked_total = 0
        self.masking_errors_total = 0
        self.tokens_out_total = 0
        self.last_request_at: float | None = None
        self.last_client: str | None = None
        self.by_client: dict[str, dict[str, int]] = {}
        self._rate = 0.0
        self._last_token_ts: float | None = None
        self._lock = threading.Lock()

    def _client(self, label: str) -> dict[str, int]:
        c = self.by_client.get(label)
        if c is None:
            c = {"requests": 0, "tokens": 0}
            self.by_client[label] = c
        return c

    def record_request(
        self, client_label: str, entities_masked: int, now: float | None = None
    ) -> None:
        now = time.time() if now is None else now
        with self._lock:
            self.requests_masked_total += 1
            self.entities_masked_total += max(0, entities_masked)
            self.last_request_at = now
            self.last_client = client_label
            self._client(client_label)["requests"] += 1

    def record_masking_error(self, now: float | None = None) -> None:
        with self._lock:
            self.masking_errors_total += 1

    def record_tokens(self, client_label: str, n: int, now: float | None = None) -> None:
        if n <= 0:
            return
        now = time.time() if now is None else now
        with self._lock:
            self.tokens_out_total += n
            self._client(client_label)["tokens"] += n
            if self._last_token_ts is None:
                self._rate = float(n)  # rough seed: ≈ n tokens over the first second
            else:
                dt = max(now - self._last_token_ts, 1e-3)
                inst = n / dt
                alpha = 1.0 - math.exp(-dt / _TAU)
                self._rate = alpha * inst + (1.0 - alpha) * self._rate
            self._last_token_ts = now

    def _decayed_rate(self, now: float) -> float:
        if self._last_token_ts is None:
            return 0.0
        dt = max(now - self._last_token_ts, 0.0)
        return self._rate * math.exp(-dt / _TAU)

    def tokens_per_sec(self, now: float | None = None) -> float:
        now = time.time() if now is None else now
        with self._lock:
            return self._decayed_rate(now)

    def snapshot(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        with self._lock:
            return {
                "started_at": self.started_at,
                "uptime_sec": max(0.0, now - self.started_at),
                "requests_masked_total": self.requests_masked_total,
                "entities_masked_total": self.entities_masked_total,
                "masking_errors_total": self.masking_errors_total,
                "tokens_out_total": self.tokens_out_total,
                "tokens_per_sec": round(self._decayed_rate(now), 1),
                "last_request_at": self.last_request_at,
                "last_client": self.last_client,
                "by_client": {k: dict(v) for k, v in self.by_client.items()},
            }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_metrics.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add anon_proxy/metrics.py tests/test_metrics.py
git commit -m "feat: add ProxyMetrics accumulator for status telemetry"
```

---

### Task 2: Agent classification

**Files:**
- Create: `anon_proxy/client_id.py`
- Test: `tests/test_client_id.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `classify_client(headers: dict[str, str]) -> str` — `headers` keys are lowercased. Returns one of `"Claude Code"`, `"Codex"`, `"Anthropic SDK"`, `"OpenAI SDK"`, a raw product token, or `"unknown"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_client_id.py
import pytest

from anon_proxy.client_id import classify_client


@pytest.mark.parametrize("headers, expected", [
    ({"user-agent": "claude-cli/1.2.3 (external, cli)", "x-app": "cli"}, "Claude Code"),
    ({"user-agent": "codex_cli_rs/0.4.0"}, "Codex"),
    ({"originator": "codex_cli_rs", "user-agent": "reqwest/0.12"}, "Codex"),
    ({"user-agent": "Anthropic/Python 0.96.0",
      "x-stainless-lang": "python",
      "x-stainless-package-version": "0.96.0",
      "anthropic-version": "2023-06-01"}, "Anthropic SDK"),
    ({"user-agent": "OpenAI/Python 1.40.0",
      "x-stainless-lang": "python",
      "x-stainless-package-version": "1.40.0"}, "OpenAI SDK"),
    ({"user-agent": "curl/8.4.0"}, "curl"),
    ({}, "unknown"),
])
def test_classify_client(headers, expected):
    assert classify_client(headers) == expected
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_client_id.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'anon_proxy.client_id'`

- [ ] **Step 3: Write the implementation**

```python
# anon_proxy/client_id.py
"""Classify the calling agent from request headers.

Pure function over a lowercased-key header dict. Stores only the resulting
label — never the raw headers (which carry auth) and never request content.
"""

from __future__ import annotations


def classify_client(headers: dict[str, str]) -> str:
    ua = headers.get("user-agent", "")
    ua_l = ua.lower()
    originator = headers.get("originator", "").lower()

    if "claude-cli" in ua_l:
        return "Claude Code"
    if "codex" in originator or "codex" in ua_l:
        return "Codex"

    has_stainless = any(k.startswith("x-stainless") for k in headers)
    if has_stainless or "anthropic-version" in headers:
        pkg = headers.get("x-stainless-package-version", "").lower()
        if "anthropic-version" in headers or "anthropic" in ua_l or "anthropic" in pkg:
            return "Anthropic SDK"
        return "OpenAI SDK"

    if ua:
        token = ua.split("/", 1)[0].strip()
        return token or "unknown"
    return "unknown"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_client_id.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add anon_proxy/client_id.py tests/test_client_id.py
git commit -m "feat: classify calling agent (Claude Code / Codex / SDK) from headers"
```

---

### Task 3: Token-count helpers

**Files:**
- Create: `anon_proxy/tokens.py`
- Test: `tests/test_tokens.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `approx_tokens_from_text(text: str) -> int` — `0` for empty, else `max(1, round(len(text)/4))`.
  - `extract_output_tokens(adapter_name: str, resp: dict) -> int | None` — reads `usage.output_tokens` (anthropic) / `usage.completion_tokens` (openai); `None` if absent.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_tokens.py
from anon_proxy.tokens import approx_tokens_from_text, extract_output_tokens


def test_approx_tokens():
    assert approx_tokens_from_text("") == 0
    assert approx_tokens_from_text("a") == 1          # rounds up off the floor
    assert approx_tokens_from_text("x" * 40) == 10


def test_extract_anthropic_output_tokens():
    resp = {"usage": {"input_tokens": 5, "output_tokens": 42}}
    assert extract_output_tokens("anthropic", resp) == 42


def test_extract_openai_output_tokens():
    resp = {"usage": {"prompt_tokens": 5, "completion_tokens": 17}}
    assert extract_output_tokens("openai", resp) == 17


def test_extract_returns_none_when_absent():
    assert extract_output_tokens("anthropic", {}) is None
    assert extract_output_tokens("openai", {"usage": {}}) is None
    assert extract_output_tokens("anthropic", {"usage": "nope"}) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_tokens.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'anon_proxy.tokens'`

- [ ] **Step 3: Write the implementation**

```python
# anon_proxy/tokens.py
"""Output-token measurement helpers.

Two sources: exact `usage` from a provider response (non-streaming), and a
character-based approximation (~4 chars/token) for streamed output where no
usage field is available.
"""

from __future__ import annotations


def approx_tokens_from_text(text: str) -> int:
    if not text:
        return 0
    return max(1, round(len(text) / 4))


def extract_output_tokens(adapter_name: str, resp: dict) -> int | None:
    usage = resp.get("usage") if isinstance(resp, dict) else None
    if not isinstance(usage, dict):
        return None
    key = "output_tokens" if adapter_name == "anthropic" else "completion_tokens"
    v = usage.get(key)
    return int(v) if isinstance(v, (int, float)) else None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_tokens.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add anon_proxy/tokens.py tests/test_tokens.py
git commit -m "feat: add output-token count helpers (usage + char approximation)"
```

---

### Task 4: `/_status` endpoint + metrics on app.state

**Files:**
- Modify: `anon_proxy/server.py` (imports; `build_app` signature + lifespan; add `status_endpoint`; register route before catch-all; `main()` wiring)
- Test: `tests/test_status_endpoint.py`

**Interfaces:**
- Consumes: `ProxyMetrics` (Task 1).
- Produces:
  - `build_app(..., metrics: ProxyMetrics | None = None, backend: str = "auto", listen_addr: str | None = None, http_client: "httpx.AsyncClient | None" = None) -> Starlette` — new keyword-only-friendly params appended (all existing calls keep working).
  - `app.state.metrics: ProxyMetrics`, `app.state.backend: str`, `app.state.listen_addr: str | None`.
  - `GET /_status` → JSON: `metrics.snapshot()` merged with `{"status": "running", "listen_addr", "providers": sorted list, "backend", "store": int}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_status_endpoint.py
import json

from starlette.testclient import TestClient

from anon_proxy.metrics import ProxyMetrics
from anon_proxy.server import build_app


def test_status_reports_metrics_and_static_facts():
    metrics = ProxyMetrics(started_at=0.0)
    metrics.record_request("Claude Code", entities_masked=2, now=1.0)
    metrics.record_tokens("Claude Code", 40, now=1.0)
    app = build_app(metrics=metrics, backend="mps", listen_addr="127.0.0.1:8080")
    with TestClient(app) as client:
        resp = client.get("/_status")
    assert resp.status_code == 200
    body = json.loads(resp.text)
    assert body["status"] == "running"
    assert body["backend"] == "mps"
    assert body["listen_addr"] == "127.0.0.1:8080"
    assert body["requests_masked_total"] == 1
    assert body["entities_masked_total"] == 2
    assert body["tokens_out_total"] == 40
    assert body["last_client"] == "Claude Code"
    assert "anthropic" in body["providers"] and "openai" in body["providers"]
    assert body["store"] == 0


def test_status_route_not_treated_as_provider():
    # Without an explicit route, "/_status" would dispatch as provider "_status"
    # and return a 400 provider error. Assert it is the status endpoint instead.
    app = build_app(metrics=ProxyMetrics(started_at=0.0))
    with TestClient(app) as client:
        resp = client.get("/_status")
    assert resp.status_code == 200
    assert json.loads(resp.text)["status"] == "running"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_status_endpoint.py -v`
Expected: FAIL — `build_app()` has no `metrics`/`backend`/`listen_addr` params (TypeError), or `/_status` returns a 400 provider error.

- [ ] **Step 3: Implement — edit `anon_proxy/server.py`**

Add the import near the other `anon_proxy` imports (top of file):

```python
from anon_proxy.metrics import ProxyMetrics
```

Change the `build_app` signature and lifespan. Replace the current `def build_app(...)` header and its `lifespan` body with:

```python
def build_app(
    masker: Masker | None = None,
    extra_upstreams: dict[str, UpstreamConfig] | None = None,
    debug: bool = False,
    store_path: str | None = None,
    metrics: ProxyMetrics | None = None,
    backend: str = "auto",
    listen_addr: str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> Starlette:
    """Build the Starlette application.

    Args:
        masker: PII masker instance (created if None)
        extra_upstreams: Additional upstream providers configured via CLI
        debug: Enable debug logging
        store_path: Persistent store path to save after new mappings.
        metrics: Activity metrics accumulator (created if None).
        backend: PII backend label, surfaced on /_status.
        listen_addr: "host:port" label, surfaced on /_status.
        http_client: Injected AsyncClient (tests); a fresh one is made if None.
    """
    masker = masker or Masker()
    metrics = metrics or ProxyMetrics()
    all_upstreams = {**BUILT_IN_UPSTREAMS, **(extra_upstreams or {})}

    @asynccontextmanager
    async def lifespan(app: Starlette):
        owns_client = http_client is None
        client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(600.0, connect=10.0)
        )
        try:
            app.state.client = client
            app.state.masker = masker
            app.state.debug = debug
            app.state.upstreams = all_upstreams
            app.state.store_path = store_path
            app.state.metrics = metrics
            app.state.backend = backend
            app.state.listen_addr = listen_addr
            yield
        finally:
            if owns_client:
                await client.aclose()

    async def status_endpoint(request: Request) -> Response:
        st = request.app.state
        snap = st.metrics.snapshot()
        snap.update({
            "status": "running",
            "listen_addr": st.listen_addr,
            "providers": sorted(st.upstreams.keys()),
            "backend": st.backend,
            "store": len(st.masker.store),
        })
        return Response(
            content=json.dumps(snap, indent=2),
            media_type="application/json",
        )
```

Then, still inside `build_app`, replace the `routes = [...]` / `return Starlette(...)` block with a version that registers `/_status` **before** the catch-all:

```python
    routes = [
        Route("/_status", status_endpoint, methods=["GET"]),
        Route(
            "/{path:path}",
            dispatch,
            methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
        ),
    ]
    return Starlette(routes=routes, lifespan=lifespan)
```

(The `dispatch` function definition stays exactly where it is, between the lifespan and the routes.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_status_endpoint.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Wire `main()` to pass real values**

In `main()`, find the `app = build_app(...)` call and replace it with:

```python
    app = build_app(
        masker=masker,
        extra_upstreams=extra_upstreams,
        debug=args.debug,
        store_path=args.store,
        metrics=ProxyMetrics(),
        backend=args.backend,
        listen_addr=f"{args.host}:{args.port}",
    )
```

Then add a line to the startup banner so operators know the endpoint exists.
Find the `f"  backend: {backend_display}\n"` line in the `print(...)` banner and
insert immediately after it:

```python
        f"  status:  http://{args.host}:{args.port}/_status\n"
```

- [ ] **Step 6: Collection check + full suite**

Run: `uv run pytest tests/ --collect-only -q 2>&1 | tail -5`
Expected: 0 errors during collection.

Run: `uv run pytest tests/ -q`
Expected: all pass (existing `test_mapping.py`, `test_store_cli.py` plus the new files).

- [ ] **Step 7: Commit**

```bash
git add anon_proxy/server.py tests/test_status_endpoint.py
git commit -m "feat: add GET /_status endpoint backed by ProxyMetrics"
```

---

### Task 5: Instrument `_handle_proxy` (requests, entities, client, tokens, alarm)

**Files:**
- Modify: `anon_proxy/server.py` (`_handle_proxy`: wrap masking, record request/tokens; streaming token hook)
- Test: `tests/test_proxy_instrumentation.py`

**Interfaces:**
- Consumes: `ProxyMetrics` (Task 1), `classify_client` (Task 2), `extract_output_tokens` (Task 3).
- Produces: no new public symbols — behavior only. After a masked non-streaming request, `app.state.metrics` reflects `requests_masked_total += 1`, `entities_masked_total += store delta`, `last_client` set, `tokens_out_total += usage.output_tokens`. A masking exception increments `masking_errors_total` and returns HTTP 502 without contacting upstream (fail closed).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_proxy_instrumentation.py
import json

import httpx
import pytest
from starlette.testclient import TestClient

from anon_proxy.masker import Masker
from anon_proxy.metrics import ProxyMetrics
from anon_proxy.server import build_app


class _StubFilter:
    """Detector stub: flags the exact substring 'Alice' as a PERSON."""
    def detect(self, text):
        from anon_proxy.privacy_filter import PIIEntity
        out = []
        start = text.find("Alice")
        if start != -1:
            out.append(PIIEntity(start=start, end=start + 5, label="PERSON",
                                  text="Alice", score=0.99))
        return out


def _anthropic_response():
    return httpx.Response(
        200,
        headers={"content-type": "application/json"},
        json={
            "id": "msg_1", "type": "message", "role": "assistant",
            "content": [{"type": "text", "text": "Hello <PERSON_1>"}],
            "usage": {"input_tokens": 10, "output_tokens": 25},
        },
    )


def _client_with_upstream(metrics, masker, handler):
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    app = build_app(masker=masker, metrics=metrics, http_client=http_client)
    return TestClient(app)


def test_successful_request_records_metrics():
    metrics = ProxyMetrics(started_at=0.0)
    masker = Masker(filter=_StubFilter())
    client = _client_with_upstream(
        metrics, masker, lambda req: _anthropic_response()
    )
    with client:
        resp = client.post(
            "/anthropic/v1/messages",
            headers={"user-agent": "claude-cli/1.2.3 (external, cli)"},
            json={"model": "claude-3", "messages":
                  [{"role": "user", "content": "Call Alice now"}]},
        )
    assert resp.status_code == 200
    snap = metrics.snapshot()
    assert snap["requests_masked_total"] == 1
    assert snap["entities_masked_total"] == 1          # 'Alice' -> one store entry
    assert snap["last_client"] == "Claude Code"
    assert snap["tokens_out_total"] == 25              # from usage.output_tokens


def test_masking_error_trips_alarm_and_fails_closed():
    metrics = ProxyMetrics(started_at=0.0)

    class _BoomFilter:
        def detect(self, text):
            raise RuntimeError("detector exploded")

    contacted = {"upstream": False}

    def handler(req):
        contacted["upstream"] = True
        return _anthropic_response()

    client = _client_with_upstream(metrics, Masker(filter=_BoomFilter()), handler)
    with client:
        resp = client.post(
            "/anthropic/v1/messages",
            json={"model": "c", "messages": [{"role": "user", "content": "hi Alice"}]},
        )
    assert resp.status_code == 502
    assert metrics.snapshot()["masking_errors_total"] == 1
    assert contacted["upstream"] is False              # never forwarded unmasked
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_proxy_instrumentation.py -v`
Expected: FAIL — no metrics recorded (counts stay 0) / masking exception currently 500s and still reaches upstream logic, so assertions fail.

- [ ] **Step 3: Implement — edit `_handle_proxy` in `anon_proxy/server.py`**

Add imports near the other `anon_proxy` imports:

```python
from anon_proxy.client_id import classify_client
from anon_proxy.tokens import extract_output_tokens
```

In `_handle_proxy`, grab metrics and classify the client. Find:

```python
    masker: Masker = request.app.state.masker
    debug: bool = request.app.state.debug
```

and insert directly below:

```python
    metrics = request.app.state.metrics
    client_label = classify_client({k.lower(): v for k, v in request.headers.items()})
```

Replace the masking block. Find:

```python
    # Mask the request
    store_before = len(masker.store)
    masked = adapter.mask_request(body, masker)
    if debug:
        new_entries = masker.store.items()[store_before:]
        _log_request(upstream_config.name, api_path, body, masked, new_entries)
```

with (wrap the mask call; fail closed on error; record the request):

```python
    # Mask the request. Masking failure fails CLOSED — never forward unmasked.
    store_before = len(masker.store)
    try:
        masked = adapter.mask_request(body, masker)
    except Exception:
        metrics.record_masking_error()
        print("error: masking failed; refusing to forward unmasked", file=sys.stderr)
        return Response(
            content=json.dumps({"error": "anon-proxy: masking failed; request blocked"}),
            status_code=502,
            media_type="application/json",
        )
    metrics.record_request(client_label, len(masker.store) - store_before)
    if debug:
        new_entries = masker.store.items()[store_before:]
        _log_request(upstream_config.name, api_path, body, masked, new_entries)
```

Add a streaming token hook. Find the streaming `body_iter` setup:

```python
        async def body_iter():
            upstream_buf: list[str] = []
            client_buf: list[str] = []
            try:
                async for out in adapter.transform_stream(
                    upstream_resp.aiter_bytes(),
                    masker,
                    on_upstream_text=upstream_buf.append if debug else None,
                    on_client_text=client_buf.append if debug else None,
                ):
                    yield out
```

Replace it with a version that always counts client-facing tokens:

```python
        async def body_iter():
            upstream_buf: list[str] = []
            client_buf: list[str] = []
            tok_carry = {"chars": 0}

            def on_client(text: str) -> None:
                tok_carry["chars"] += len(text)
                whole = tok_carry["chars"] // 4
                if whole:
                    tok_carry["chars"] -= whole * 4
                    metrics.record_tokens(client_label, whole)
                if debug:
                    client_buf.append(text)

            try:
                async for out in adapter.transform_stream(
                    upstream_resp.aiter_bytes(),
                    masker,
                    on_upstream_text=upstream_buf.append if debug else None,
                    on_client_text=on_client,
                ):
                    yield out
```

(Leave the `finally:` block of `body_iter` unchanged.)

Add non-streaming token recording. Find:

```python
            unmasked = adapter.unmask_response(resp_json, masker)
            if debug:
                _log_response(resp_json, unmasked)
            await _maybe_save_store(request.app.state, store_before)
```

and insert the token record between the unmask and the save:

```python
            unmasked = adapter.unmask_response(resp_json, masker)
            if debug:
                _log_response(resp_json, unmasked)
            n_out = extract_output_tokens(upstream_config.adapter, resp_json)
            if n_out:
                metrics.record_tokens(client_label, n_out)
            await _maybe_save_store(request.app.state, store_before)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_proxy_instrumentation.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Full suite + collection check**

Run: `uv run pytest tests/ --collect-only -q 2>&1 | tail -5`
Expected: 0 errors.

Run: `uv run pytest tests/ -q`
Expected: all pass.

- [ ] **Step 6: Manual end-to-end smoke (evidence for handoff)**

Start the proxy and curl the endpoint:

```bash
uv run python -m anon_proxy.server --port 8080 &
sleep 3
curl -s http://127.0.0.1:8080/_status | python3 -m json.tool
kill %1
```

Expected: JSON with `"status": "running"`, `"requests_masked_total": 0`, providers listing `anthropic`/`openai`, `"tokens_per_sec": 0.0`.

- [ ] **Step 7: Commit**

```bash
git add anon_proxy/server.py tests/test_proxy_instrumentation.py
git commit -m "feat: record requests, PII, agent, tokens, and mask-error alarm in proxy"
```

---

## Self-Review

**Spec coverage (server-side portion):**
- `ProxyMetrics` fields + methods → Task 1. ✓
- Agent classification → Task 2. ✓
- Token measurement (exact usage + char fallback) → Task 3 (helpers) + Task 5 (wired: non-streaming usage, streaming char/4). ✓
- `/_status` internal non-proxied route, counts-only → Task 4. ✓
- `entities_masked_total` as store delta (zero adapter changes) → Task 5 uses `len(masker.store) - store_before`. ✓
- `masking_errors_total` alarm source, fail-closed → Task 5 (try/except → 502, no upstream). ✓
- Telemetry never breaks masking / never leaks content → metrics hold only counts; snapshot key-set asserted in Task 1; masking failure blocks rather than forwarding. ✓
- k8s-probe reuse → `/_status` returns 200 JSON when up. ✓

**Deferred to Plan 02 (menu bar):** rumps app, dino rendering, theming/holidays, supervise, launchd, `--watch` fallback. Plan 02 consumes only the `/_status` JSON defined here.

**Placeholder scan:** none — every step has full code/commands.

**Type consistency:** `classify_client(dict)`, `extract_output_tokens(str, dict) -> int | None`, `ProxyMetrics.record_*`/`snapshot` names match between definition (Tasks 1–3) and use (Tasks 4–5). `build_app` new params are used consistently in Task 4 test and `main()` wiring.
