# PR 04: Run detection off the event loop (+ thread safety)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans or
> superpowers:subagent-driven-development.

**Goal:** Torch inference currently runs synchronously inside the async handler
(`server.py:455-459`), so every concurrent Claude Code request and every
in-flight SSE stream stalls behind each forward pass. Offload masking to a
worker thread and make the shared state it touches thread-safe.

**Architecture:** `adapter.mask_request` moves to `asyncio.to_thread(...)`
(contextvars — including the telemetry scope — propagate into `to_thread`
automatically). That makes `PIIStore`, the Masker caches, and the HF pipeline
reachable from multiple threads, so: one `threading.RLock` in `PIIStore`, one in
`Masker` guarding both LRU caches, and one in `PrivacyFilter` serializing
pipeline calls (GPU inference stays serialized — the win is that the event loop
and cache-hit requests no longer wait behind it). Response unmasking is cheap
regex — stays inline.

**Tech stack:** `threading.RLock`, `asyncio.to_thread`, `ThreadPoolExecutor` in
tests (per ~/.claude/docs/testing.md concurrency rules).

## Global constraints

- See overview plan. Branch: `perf/detection-off-event-loop` off `main`.
- High-risk change class (concurrency) → concurrent-execution tests are
  mandatory, not optional.

---

### Task 1: Thread-safe PIIStore

**Files:**
- Modify: `anon_proxy/mapping.py` (`PIIStore.__init__`, `get_or_create`)
- Test: `tests/test_mapping.py` (new)

**Interfaces:**
- Produces: `PIIStore.get_or_create(label, value) -> Placeholder`, unchanged
  signature, now safe under concurrent callers: same (label, value) never gets
  two different tokens, indexes never collide.

- [ ] **Step 1: Failing concurrency test**

```python
def test_get_or_create_is_thread_safe():
    from concurrent.futures import ThreadPoolExecutor
    store = PIIStore()
    values = [f"person-{i % 50}" for i in range(1000)]  # heavy duplication

    with ThreadPoolExecutor(max_workers=16) as ex:
        tokens = list(ex.map(lambda v: store.get_or_create("PERSON", v).token, values))

    # Same value -> same token, always.
    by_value: dict[str, set[str]] = {}
    for v, t in zip(values, tokens):
        by_value.setdefault(v, set()).add(t)
    assert all(len(ts) == 1 for ts in by_value.values())
    # 50 distinct values -> exactly indexes 1..50, no gaps or dupes.
    assert len(store) == 50
    indexes = sorted(int(t.rstrip(">").rsplit("_", 1)[1]) for ts in by_value.values() for t in ts)
    assert indexes == list(range(1, 51))
```

Run: `uv run pytest tests/test_mapping.py -q -k thread_safe` — this may pass
flakily under the GIL; that's fine, it's the regression guard. It must pass
deterministically after the lock lands.

- [ ] **Step 2: Add the lock**

```python
import threading

class PIIStore:
    def __init__(self) -> None:
        self._forward: dict[tuple[str, str], Placeholder] = {}
        self._reverse: dict[str, str] = {}
        self._counters: dict[str, int] = {}
        self._lock = threading.RLock()

    def get_or_create(self, label: str, value: str) -> Placeholder:
        if not value or not value.strip():
            raise ValueError(
                "PIIStore.get_or_create: value must be non-empty after stripping whitespace"
            )
        normalized_label = normalize_label(label)
        key = (normalized_label, _canonical(value))
        with self._lock:
            existing = self._forward.get(key)
            if existing is not None:
                return existing
            index = self._counters.get(normalized_label, 0) + 1
            self._counters[normalized_label] = index
            token = f"<{normalized_label}_{index}>"
            ph = Placeholder(label=normalized_label, index=index, token=token)
            self._forward[key] = ph
            self._reverse[token] = value
            return ph
```

Also wrap `tokens()`, `items()`, `to_dict()` bodies in `with self._lock:` (they
snapshot dicts that another thread may be mutating). Update the class docstring
("Not thread-safe" → describe the lock). `from_dict` mutates a fresh instance
before publication — no lock needed, note that in a comment.

- [ ] **Step 3: Full suite, commit**

`uv run pytest tests/ -q` → pass.
`git commit -m "feat: make PIIStore thread-safe"` (include both files).

### Task 2: Thread-safe Masker caches + serialized pipeline

**Files:**
- Modify: `anon_proxy/masker.py` (`__init__`, `mask`, `_cache_result`, `mask_obj`)
- Modify: `anon_proxy/privacy_filter.py` (`__init__`, `detect`, `detect_raw`)
- Test: `tests/test_masker.py` (new)

**Interfaces:**
- Produces: `Masker.mask` / `mask_obj` safe under concurrent threads;
  `PrivacyFilter.detect` serialized by an internal `threading.Lock` named
  `self._infer_lock` (PR 05 reuses this exact attribute).

- [ ] **Step 1: Failing test**

```python
def test_concurrent_mask_same_text_yields_one_placeholder(
    self, make_masker, fake_pipeline
):
    from concurrent.futures import ThreadPoolExecutor
    m = make_masker()
    text = "call Alice now"
    fake_pipeline.set(text, [span("private_person", 5, 10, word="Alice")])
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda _: m.mask(text), range(64)))
    assert len(set(results)) == 1
    assert results[0] == "call <PERSON_1> now"
```

- [ ] **Step 2: Implement**

`Masker.__init__`: add `self._cache_lock = threading.RLock()`. In `mask`, take
the lock around the cache *read* block and around `_cache_result`; do NOT hold
it during detection (that would re-serialize everything — the point is only
dict-consistency). In `mask_obj`, take it around both `_block_cache` accesses.
Two threads may race to detect the same uncached text and both write the same
cache entry — harmless because placeholder allocation in the store is
idempotent per (label, value) after Task 1; say so in a comment.

`PrivacyFilter.__init__`: add `self._infer_lock = threading.Lock()`. In
`detect` and `detect_raw`, wrap each `self._pipe(...)` call:
`with self._infer_lock: results = self._pipe(chunk)`.

- [ ] **Step 3: Full suite, commit**

`uv run pytest tests/ -q` → pass. Commit: `"feat: make Masker caches and pipeline access thread-safe"`.

### Task 3: Offload mask_request in the server

**Files:**
- Modify: `anon_proxy/server.py:449-459` (both branches of the capture
  conditional) — and the non-streaming `unmask_response` stays inline.
- Test: `tests/test_server.py` (new)

**Interfaces:**
- Consumes: thread-safe Masker from Tasks 1–2.
- Produces: identical HTTP behavior; event loop free during detection.

- [ ] **Step 1: Failing test — event loop stays responsive during masking**

```python
@pytest.mark.anyio
async def test_event_loop_not_blocked_during_mask(monkeypatch, app_factory):
    # app_factory: however tests/test_server.py builds the Starlette app with a
    # stub masker today — reuse that fixture. Make mask_request take 200ms of
    # *blocking* time, fire two requests concurrently, and assert wall-clock
    # is ~200ms (parallel via threads), not ~400ms (serialized on the loop).
    import time as _time

    def slow_mask_request(body, masker):
        _time.sleep(0.2)
        return body

    monkeypatch.setattr(anthropic_adapter, "mask_request", slow_mask_request)
    t0 = time.perf_counter()
    r1, r2 = await asyncio.gather(post_messages(app), post_messages(app))
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.35, f"requests serialized on the event loop: {elapsed:.2f}s"
```

Adapt `post_messages`/`app` to the existing test_server harness (it already has
an httpx-mock/ASGI transport pattern — follow it).

- [ ] **Step 2: Implement**

In `_handle_proxy`, replace the two `adapter.mask_request(body, masker)` call
sites with `await asyncio.to_thread(adapter.mask_request, body, masker)`:

```python
    if capture is not None:
        with telemetry_scope() as calls:
            t_mask = time.perf_counter()
            masked = await asyncio.to_thread(adapter.mask_request, body, masker)
            mask_request_ms = (time.perf_counter() - t_mask) * 1000
            mask_calls = list(calls)
    else:
        masked = await asyncio.to_thread(adapter.mask_request, body, masker)
```

(contextvars propagate into `to_thread`, so `telemetry_scope` still collects.)

- [ ] **Step 3: Full suite + live check, commit**

`uv run pytest tests/ -q` → pass. Live: proxy + Claude Code, confirm side-call
requests no longer queue behind a big file-read mask (subjective but visible in
`--metrics` proxy-ms lines). Commit:

```bash
git commit -m "perf: run request masking in a worker thread

Torch inference was blocking the asyncio event loop, serializing all
concurrent requests and stalling in-flight SSE streams behind every
forward pass (issue #6). Store/caches/pipeline gained locks in the
previous commits so the shared Masker is safe off-loop."
```
