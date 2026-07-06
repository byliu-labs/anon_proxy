# PR 07: Surface prompt-cache usage in `--metrics`

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans or
> superpowers:subagent-driven-development.

**Goal:** The #12 (429) leading hypothesis is prompt-cache degradation → input
token blowup → ITPM limit. Make the diagnosis a `--metrics` run: log
`input / cache_read / cache_creation` tokens per turn so a dead cache is
visible immediately.

**Architecture:** Non-streaming: read `resp_json["usage"]` (Anthropic:
`input_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`;
OpenAI: `prompt_tokens`, `prompt_tokens_details.cached_tokens`). Streaming
(Anthropic): usage arrives in the `message_start` event, which
`transform_stream` already parses — add an optional `on_usage` callback so the
server can log it without a second SSE parser. OpenAI streaming only reports
usage with `stream_options.include_usage`; handle it if present, else skip.

## Global constraints

- See overview plan. Branch: `feat/cache-usage-metrics` off `main`.

---

### Task 1: Usage extraction helper + non-streaming logging

**Files:**
- Modify: `anon_proxy/server.py` (`_log_metrics`, non-streaming branch)
- Test: `tests/test_server.py`

**Interfaces:**
- Produces: `_extract_usage(resp_json: dict) -> dict | None` returning
  `{"input": int, "cache_read": int, "cache_creation": int}` (zeros when the
  provider omits a field); `_log_metrics(provider, e2e, upstream, usage=None)`.

- [ ] **Step 1: Failing tests**

```python
class TestExtractUsage:
    def test_anthropic_usage(self):
        j = {"usage": {"input_tokens": 900, "cache_read_input_tokens": 8000,
                       "cache_creation_input_tokens": 120, "output_tokens": 50}}
        assert _extract_usage(j) == {"input": 900, "cache_read": 8000,
                                     "cache_creation": 120}

    def test_openai_usage(self):
        j = {"usage": {"prompt_tokens": 900, "completion_tokens": 10,
                       "prompt_tokens_details": {"cached_tokens": 700}}}
        assert _extract_usage(j) == {"input": 900, "cache_read": 700,
                                     "cache_creation": 0}

    def test_no_usage_returns_none(self):
        assert _extract_usage({}) is None
```

- [ ] **Step 2: Implement**

```python
def _extract_usage(resp_json: dict) -> dict | None:
    """Normalize Anthropic/OpenAI usage blocks for the metrics line."""
    u = resp_json.get("usage")
    if not isinstance(u, dict):
        return None
    if "input_tokens" in u:  # Anthropic
        return {"input": u.get("input_tokens", 0),
                "cache_read": u.get("cache_read_input_tokens", 0),
                "cache_creation": u.get("cache_creation_input_tokens", 0)}
    if "prompt_tokens" in u:  # OpenAI
        details = u.get("prompt_tokens_details") or {}
        return {"input": u.get("prompt_tokens", 0),
                "cache_read": details.get("cached_tokens", 0),
                "cache_creation": 0}
    return None
```

Extend `_log_metrics(provider, e2e, upstream, usage: dict | None = None)` to
append, when usage is present:
`  tokens: in=900 cache_read=8000 cache_create=120`.
Call it with `_extract_usage(resp_json)` in the non-streaming branch (both
existing `_log_metrics` call sites there).

- [ ] **Step 3: Full suite, commit** — `"feat: log token/cache usage in --metrics (non-streaming)"`.

### Task 2: Streaming usage via adapter callback

**Files:**
- Modify: `anon_proxy/adapters/anthropic.py` (`transform_stream`,
  `_transform_event`), `anon_proxy/adapters/openai.py` (same), `anon_proxy/server.py`
  (streaming `body_iter`, `finally` block)
- Test: `tests/test_adapter_streaming.py`

**Interfaces:**
- Produces: `transform_stream(..., on_usage: Callable[[dict], None] | None = None)`
  — fired at most twice (Anthropic `message_start` carries input+cache fields;
  `message_delta` carries output tokens; merge dicts in the server).

- [ ] **Step 1: Failing test**

```python
@pytest.mark.anyio
async def test_stream_reports_usage(make_masker, store):
    m = make_masker()
    events = sse_bytes([  # reuse this file's existing SSE fixture helper
        ("message_start", {"type": "message_start", "message": {
            "usage": {"input_tokens": 12, "cache_read_input_tokens": 300,
                      "cache_creation_input_tokens": 0}}}),
        ("message_stop", {"type": "message_stop"}),
    ])
    seen: list[dict] = []
    async for _ in anthropic_adapter.transform_stream(
        aiter_of([events]), m, on_usage=seen.append):
        pass
    assert seen and seen[0]["input_tokens"] == 12
    assert seen[0]["cache_read_input_tokens"] == 300
```

- [ ] **Step 2: Implement**

In `_transform_event`, before the `content_block_start` branch:

```python
    if event_type == "message_start" and on_usage is not None:
        usage = (data.get("message") or {}).get("usage")
        if isinstance(usage, dict):
            on_usage(usage)
```

Thread `on_usage` through `transform_stream` → `_transform_event` in both
adapters (OpenAI: fire when a chunk has a top-level `"usage"` dict — present
only with `stream_options.include_usage`). In `server.py`'s streaming path,
collect into `usage_acc: list[dict]`, and in the `finally`-adjacent metrics
call: `_log_metrics(..., usage=_extract_usage({"usage": merged}) if usage_acc
else None)` where `merged = {k: v for d in usage_acc for k, v in d.items()}`.

- [ ] **Step 3: Full suite, live check, commit**

`uv run pytest tests/ -q` → pass. Live: `--metrics` + Claude Code turn → line
shows `cache_read=...`. **This is the #12 diagnostic:** if `cache_read=0` on
every turn of a long session, prompt caching is dead through the proxy — file
the finding on #12 with the log lines. Commit:
`"feat: report streaming usage (incl. cache_read) in --metrics"`.
