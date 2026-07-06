# PR 02: Mask `count_tokens` request bodies

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans or
> superpowers:subagent-driven-development.

**Goal:** `count_tokens` requests carry the full message history; mask them like
any other request instead of passing them through raw.

**Architecture:** Delete the `count_tokens` early-return in
`_should_mask_request` (`server.py:692-699`). The body then matches the
`"messages" in body` fallback and flows through the normal mask path. The
response (`{"input_tokens": N}`) contains no placeholders, so the unmask walk is
a no-op. Cost is near-zero once history blocks are in the block cache (they are
— the main request populates it).

**Why:** commit `efa6789` framed masking here as "wasted work", but the threat
model is about bytes leaving the box, not about what generates output. Claude
Code calls count_tokens constantly with the whole conversation.

## Global constraints

- See overview plan. Branch: `fix/mask-count-tokens` off `main`.

---

### Task 1: count_tokens goes through the mask path

**Files:**
- Modify: `anon_proxy/server.py:682-699` (`_should_mask_request`)
- Test: `tests/test_server.py:183-185` (existing inverted test) + new case

**Interfaces:**
- Produces: `_should_mask_request(path: str, body: dict) -> bool` — True for
  any path whose body has a `messages`/`prompt`/`content`/`input`/`text` field,
  including `/v1/messages/count_tokens`.

- [ ] **Step 1: Invert the existing test**

Replace `test_count_tokens_path_returns_false` (tests/test_server.py:183):

```python
def test_count_tokens_with_messages_is_masked(self):
    # count_tokens carries the full conversation history; the bytes leave
    # the box, so it must be masked like /v1/messages itself.
    body = {"messages": [{"role": "user", "content": "hi"}]}
    assert _should_mask_request("/v1/messages/count_tokens", body) is True

def test_count_tokens_without_pii_fields_not_masked(self):
    assert _should_mask_request("/v1/messages/count_tokens", {}) is False
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_server.py -q -k count_tokens`
Expected: first test FAILS (returns False today).

- [ ] **Step 3: Delete the fast path**

In `anon_proxy/server.py` `_should_mask_request`, remove:

```python
    if "count_tokens" in path:
        return False
```

and update the docstring: drop the "Metadata endpoints like count_tokens are
fast-tracked" paragraph; note instead that count_tokens is masked because it
carries the full history and block-cache hits make it cheap.

- [ ] **Step 4: Full suite + collection check**

Run: `uv run pytest tests/ -q` — expect all pass.

- [ ] **Step 5: Live verification (part of PR handoff, not optional)**

Start the proxy with `--debug`, run a short Claude Code turn, and confirm the
`count_tokens` POST logs a `[masked]` diff (or `(no PII detected)`) instead of
appearing only as a passthrough access-log line.

- [ ] **Step 6: Commit**

```bash
git add anon_proxy/server.py tests/test_server.py
git commit -m "fix: mask count_tokens request bodies

count_tokens requests carry the complete message history; skipping them
sent the raw conversation upstream. The block cache makes masking them
nearly free since the main request already populated it."
```
