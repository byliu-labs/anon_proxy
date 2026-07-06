# PR 06: Stop retrying 429s inside the proxy

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans or
> superpowers:subagent-driven-development.

**Goal:** The proxy retries 429s up to 3× with its own backoff
(`server.py:240-283`), and clients (Claude Code) retry on top — up to 4
upstream requests per client attempt. That amplifies the very rate-limiting it
tries to hide (issue #12) and delays the client's own correct backoff UX.
Return 429s to the client immediately, headers intact.

**Architecture:** `_upstream_request` loses the retry loop and becomes a thin
build-and-send helper (kept — it centralizes the stream/params plumbing used by
three call sites). `_parse_retry_after` dies with it. The client's Retry-After
header passes through untouched (`retry-after` is not in
`_SKIP_RESPONSE_HEADERS`).

## Global constraints

- See overview plan. Branch: `fix/no-proxy-429-retry` off `main`.

---

### Task 1: 429 passes through immediately

**Files:**
- Modify: `anon_proxy/server.py:229-283` (delete `_parse_retry_after`, simplify
  `_upstream_request`)
- Test: `tests/test_server.py:143-172` (delete the `_parse_retry_after` tests;
  replace any retry-behavior tests with a pass-through test)

**Interfaces:**
- Produces: `_upstream_request(client, method, url, *, content=None,
  headers=None, params=None, stream=False) -> httpx.Response` — no
  `max_retries` param, exactly one send.

- [ ] **Step 1: Rewrite the tests**

Delete `TestParseRetryAfter` (or equivalent class holding lines 143–172) and
any test asserting multiple upstream attempts on 429. Add:

```python
@pytest.mark.anyio
async def test_429_passes_through_with_retry_after(app_with_stub_upstream):
    # Stub upstream returns 429 with Retry-After: 7. The proxy must return
    # it to the client on the FIRST attempt, header intact, exactly one
    # upstream call — the client owns backoff, not the proxy.
    app, upstream_calls = app_with_stub_upstream(status=429,
                                                 headers={"retry-after": "7"})
    resp = await post_messages(app)
    assert resp.status_code == 429
    assert resp.headers["retry-after"] == "7"
    assert len(upstream_calls) == 1
```

(Reuse the existing test_server stub-upstream pattern; `upstream_calls` is
whatever call-recording that harness already provides.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_server.py -q -k "429"`
Expected: `len(upstream_calls) == 1` FAILS (proxy retries 3×, slowly — the
sleeps also make this test take ~7s today, which is itself the point).

- [ ] **Step 3: Implement**

Replace `_upstream_request` with:

```python
async def _upstream_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    content: bytes | None = None,
    headers: dict[str, str] | None = None,
    params: dict | None = None,
    stream: bool = False,
) -> httpx.Response:
    """Build and send one upstream request.

    Deliberately no retry logic: clients (Claude Code, SDKs) already retry
    429s with correct backoff, and a proxy-level retry multiplies upstream
    pressure while hiding the rate-limit signal from the client (issue #12).
    """
    req = client.build_request(method, url, content=content, headers=headers,
                               params=params)
    return await client.send(req, stream=stream)
```

Delete `_parse_retry_after` and the `import random` if now unused.

- [ ] **Step 4: Full suite + collection check**

`uv run pytest tests/ -q` and
`uv run pytest tests/ --collect-only -q 2>&1 | tail -3` (test_server imports
`_parse_retry_after` at line 21 — the import must be removed with the tests).

- [ ] **Step 5: Commit**

```bash
git add anon_proxy/server.py tests/test_server.py
git commit -m "fix: return 429s to the client instead of retrying in the proxy

Proxy-side retries (3x) stacked with client-side retries turned one
attempt into up to 4 upstream requests, amplifying the rate limiting in
issue #12 and hiding the 429/Retry-After signal from the client's own
backoff. The client is the right layer for this."
```
