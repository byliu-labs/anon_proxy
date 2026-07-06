# PR 08: Fail-closed masking — mask every string leaf unless whitelisted

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans or
> superpowers:subagent-driven-development. Land after PRs 01/02.

**Goal:** Today the adapters enumerate fields to mask; any unrecognized field,
block type, or API shape passes through raw (concrete instance: OpenAI
Responses API `input`). Invert: one walker masks every string leaf of the
outbound body, and an explicit whitelist names the fields allowed through
untouched. A new field can then only fail visibly (over-masked), never
invisibly (leaked).

**Architecture:** New module `anon_proxy/policy.py` with `mask_body(body,
masker, policy)` and a per-adapter `Policy` (frozen dataclass) of passthrough
rules. Adapters keep their public `mask_request` signature but delegate to the
walker; their bespoke recursive `_mask_message`/`_mask_block` walkers are
deleted. Unmasking stays as-is (blanket unmask is already fail-closed in the
right direction — extra unmask attempts are no-ops). `inject_system` in the
OpenAI adapter additionally guards: only inject when `"messages"` is present
(Responses-API bodies must not gain a bogus `messages` array).

**The policy model (keep it this simple):**
- `pass_keys: frozenset[str]` — a string VALUE is passed through when its dict
  key is in this set, at any depth. These are protocol identifiers, not prose.
- `pass_paths: frozenset[tuple[str, ...]]` — entire subtrees passed through,
  matched from the body root (e.g. `("system",)`, `("tools",)`).
- Block-type rule (Anthropic): inside `messages[*].content[*]`, a dict with
  `"type": "thinking"` or `"redacted_thinking"` passes through whole
  (signatures break if rewritten); a dict with `"type": "image"` passes its
  `source` subtree (base64 is not maskable text).
- Everything else that is a `str` gets `masker.mask(...)`.

## Global constraints

- See overview plan. Branch: `feat/fail-closed-masking` off `main`.
- The whitelists below are the security review surface of this PR — every
  entry must be justifiable as "protocol constant, not user data".

---

### Task 1: The walker

**Files:**
- Create: `anon_proxy/policy.py`
- Test: `tests/test_policy.py` (new)

**Interfaces:**
- Produces:
  `Policy(pass_keys: frozenset[str], pass_paths: frozenset[tuple[str, ...]], pass_block_types: frozenset[str], pass_block_subtrees: dict[str, str])`
  and `mask_body(body: dict, masker: Masker, policy: Policy) -> dict`.
  `masker.mask_obj` is used per `messages[*]` element for the block cache,
  exactly like the adapters do today.

- [ ] **Step 1: Failing tests (the leak-class tests are the point of the PR)**

```python
from anon_proxy.policy import Policy, mask_body

TEST_POLICY = Policy(
    pass_keys=frozenset({"model", "role", "type", "id", "name", "tool_use_id",
                         "media_type", "stop_reason", "signature"}),
    pass_paths=frozenset({("system",), ("tools",), ("metadata",)}),
    pass_block_types=frozenset({"thinking", "redacted_thinking"}),
    pass_block_subtrees={"image": "source"},
)

class TestFailClosedWalker:
    def test_unknown_field_is_masked(self, make_masker, fake_pipeline):
        # THE leak-class test: a field no adapter knows about must be masked.
        m = make_masker()
        fake_pipeline.set("Alice's data", [span("private_person", 0, 5, word="Alice")])
        body = {"model": "m", "some_future_field": "Alice's data"}
        out = mask_body(body, m, TEST_POLICY)
        assert "Alice" not in json.dumps(out)

    def test_pass_keys_survive(self, make_masker):
        m = make_masker()
        body = {"model": "claude-x", "messages": [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]}]}
        out = mask_body(body, m, TEST_POLICY)
        assert out["model"] == "claude-x"
        assert out["messages"][0]["role"] == "user"

    def test_system_and_tools_subtrees_pass(self, make_masker, fake_pipeline):
        m = make_masker()
        body = {"system": "You are X. Contact alice@x.com.",
                "tools": [{"name": "t", "description": "call alice@x.com"}]}
        out = mask_body(body, m, TEST_POLICY)
        assert out == body  # documented out-of-scope subtrees

    def test_thinking_block_passes_whole(self, make_masker):
        m = make_masker()
        blk = {"type": "thinking", "thinking": "secret Alice reasoning",
               "signature": "sig=="}
        body = {"messages": [{"role": "assistant", "content": [blk]}]}
        out = mask_body(body, m, TEST_POLICY)
        assert out["messages"][0]["content"][0] == blk

    def test_message_blocks_use_block_cache(self, make_masker, fake_pipeline):
        m = make_masker()
        msg = {"role": "user", "content": "hello"}
        body = {"messages": [msg]}
        mask_body(body, m, TEST_POLICY)
        calls_before = len(fake_pipeline.calls)
        mask_body(body, m, TEST_POLICY)   # identical → block-cache hit
        assert len(fake_pipeline.calls) == calls_before
```

- [ ] **Step 2: Implement `anon_proxy/policy.py`**

```python
"""Fail-closed outbound masking.

One rule: every string leaf of an outbound body is masked unless an explicit
policy entry passes it through. New fields/APIs can only fail visibly
(over-masked), never invisibly (leaked). Policies list protocol constants,
never user data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from anon_proxy.masker import Masker


@dataclass(frozen=True)
class Policy:
    pass_keys: frozenset[str] = frozenset()
    pass_paths: frozenset[tuple[str, ...]] = frozenset()
    pass_block_types: frozenset[str] = frozenset()
    pass_block_subtrees: dict[str, str] = field(default_factory=dict)


def mask_body(body: dict, masker: Masker, policy: Policy) -> dict:
    result = {}
    for key, value in body.items():
        if (key,) in policy.pass_paths:
            result[key] = value
        elif key == "messages" and isinstance(value, list):
            result[key] = [
                masker.mask_obj(m, lambda mm: _walk(mm, masker, policy))
                for m in value
            ]
        else:
            result[key] = _walk_kv(key, value, masker, policy)
    return result


def _walk(value: Any, masker: Masker, policy: Policy) -> Any:
    if isinstance(value, str):
        return masker.mask(value)
    if isinstance(value, dict):
        btype = value.get("type")
        if btype in policy.pass_block_types:
            return value
        sub = policy.pass_block_subtrees.get(btype)
        return {
            k: (v if k == sub or k in policy.pass_keys and isinstance(v, str)
                else _walk(v, masker, policy))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_walk(v, masker, policy) for v in value]
    return value


def _walk_kv(key: str, value: Any, masker: Masker, policy: Policy) -> Any:
    if isinstance(value, str):
        return value if key in policy.pass_keys else masker.mask(value)
    return _walk(value, masker, policy)
```

Refine while implementing until the tests pass — but the shape stays: ≤60
lines, zero adapter-specific branches, and the *only* way to skip masking is a
policy entry. (Note `_walk` on dicts must route each `(k, v)` string pair
through the pass_keys check — mirror `_walk_kv`; write it so there is exactly
one place that decides "mask or pass".)

- [ ] **Step 3: Full suite, commit** — `"feat: fail-closed mask walker + policy model"`.

### Task 2: Anthropic adapter on the walker

**Files:**
- Modify: `anon_proxy/adapters/anthropic.py` (`mask_request` delegates;
  delete `_mask_message`/`_mask_block`)
- Test: `tests/test_adapter_anthropic.py` (existing tests must still pass —
  they define the compatibility contract)

**Interfaces:**
- Produces: `ANTHROPIC_POLICY` in `anthropic.py`; `mask_request(body, masker)`
  signature unchanged.

- [ ] **Step 1: Define the policy (this list is the review surface)**

```python
ANTHROPIC_POLICY = Policy(
    pass_keys=frozenset({
        "model", "role", "type", "id", "name", "tool_use_id",
        "media_type", "stop_reason", "stop_sequence", "signature",
        "cache_control", "service_tier", "tool_choice", "container",
    }),
    pass_paths=frozenset({
        ("system",),        # documented out of scope (SECURITY.md)
        ("tools",),         # tool schemas — static
        ("metadata",),      # opaque IDs the provider correlates on
        ("mcp_servers",),   # server config, not user prose
    }),
    pass_block_types=frozenset({"thinking", "redacted_thinking"}),
    pass_block_subtrees={"image": "source", "document": "source"},
)

def mask_request(body: dict, masker: Masker) -> dict:
    return mask_body(body, masker, ANTHROPIC_POLICY)
```

- [ ] **Step 2: Run the existing adapter tests**

`uv run pytest tests/test_adapter_anthropic.py tests/test_adapter_streaming.py -q`
— failures here are the real review: each one is either (a) a walker bug, or
(b) a field the old adapter *silently leaked* that is now masked — for (b),
update the test and call it out in the PR description as a closed hole.

- [ ] **Step 3: Full suite, commit** — `"refactor: anthropic adapter masks via fail-closed policy"`.

### Task 3: OpenAI adapter on the walker + Responses-API guard

**Files:**
- Modify: `anon_proxy/adapters/openai.py`
- Test: `tests/test_adapter_openai.py` (+ new Responses-API cases)

- [ ] **Step 1: Failing tests**

```python
def test_responses_api_input_is_masked(make_masker, fake_pipeline):
    m = make_masker()
    fake_pipeline.set("I am Alice", [span("private_person", 5, 10, word="Alice")])
    body = {"model": "gpt-x", "input": "I am Alice"}
    out = openai_adapter.mask_request(body, m)
    assert "Alice" not in json.dumps(out)

def test_inject_system_skips_non_chat_bodies():
    body = {"model": "gpt-x", "input": "hello"}
    out = openai_adapter.inject_system(body, "PROMPT")
    assert "messages" not in out   # must not fabricate a messages array
```

- [ ] **Step 2: Implement**

```python
OPENAI_POLICY = Policy(
    pass_keys=frozenset({
        "model", "role", "type", "id", "name", "tool_call_id",
        "finish_reason", "logprobs", "response_format", "tool_choice",
        "user",  # opaque end-user ID for abuse detection
    }),
    pass_paths=frozenset({("tools",), ("functions",), ("instructions",)}),
    pass_block_types=frozenset(),
    pass_block_subtrees={"image_url": "image_url"},
)
```

`mask_request` delegates to `mask_body`; keep the special case that
`tool_calls[*].function.arguments` is a JSON *string* — parse → walk → re-dump
(move the existing `_mask_tool_call` JSON-string handling into a small
pre-pass, it's genuinely OpenAI-specific). Note this policy deliberately drops
the old `tools[*].function.parameters` masking (schemas are static; the old
behavior contradicted the Anthropic adapter — document in PR). `inject_system`
gains at the top:

```python
    if "messages" not in body:
        return dict(body)  # Responses API & friends: nothing to merge into
```

- [ ] **Step 3: Full suite + collection check, commit** —
`"refactor: openai adapter masks via fail-closed policy; guard inject_system"`.

### Task 4: Docs

- [ ] Update SECURITY.md in-scope section: "every string leaf is masked unless
  it appears in the adapter's passthrough policy; the policies are in
  `anon_proxy/policy.py` and the adapter modules" — and README's
  "What is NOT masked" to reference the policy constants as the source of truth.
- [ ] Commit: `"docs: describe fail-closed masking policy"`.
