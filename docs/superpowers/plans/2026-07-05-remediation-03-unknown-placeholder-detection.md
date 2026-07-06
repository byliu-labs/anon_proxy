# PR 03: Detect unknown placeholder tokens in responses

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans or
> superpowers:subagent-driven-development.

**Goal:** When the upstream model emits a placeholder-shaped token that has no
store entry (hallucinated index, e.g. z.ai's `ls -<PERSON_186>` in issue #13),
warn loudly instead of silently forwarding garbage.

**Architecture:** `Masker._sub` builds its regex from *known* tokens, so unknown
tokens never even match — add a scan of the substituted output with the existing
`_PLACEHOLDER_RE` and report tokens that still look like placeholders but have
no store entry. Report via stderr + telemetry. No strict/failing mode yet
(YAGNI until warn-mode data says otherwise).

## Global constraints

- See overview plan. Branch: `fix/unknown-placeholder-warning` off `main`.

---

### Task 1: unmask warns on unknown placeholder tokens

**Files:**
- Modify: `anon_proxy/masker.py` (`_sub`, `unmask`, `unmask_json`)
- Test: `tests/test_masker.py` (new section)

**Interfaces:**
- Produces: `Masker.unmask(text)` / `unmask_json(text)` unchanged signatures;
  side effect: one stderr line per distinct unknown token per call, and a
  telemetry entry field `"unknown_tokens": int` on unmask ops.

- [ ] **Step 1: Failing tests**

```python
class TestUnknownPlaceholderDetection:
    def test_unknown_token_warns_and_passes_through(
        self, make_masker, fake_pipeline, store, capsys
    ):
        m = make_masker()
        store.get_or_create("PERSON", "Alice")          # known: <PERSON_1>
        out = m.unmask("run ls -<PERSON_186> for <PERSON_1>")
        assert out == "run ls -<PERSON_186> for Alice"  # unknown left verbatim
        err = capsys.readouterr().err
        assert "<PERSON_186>" in err and "unknown placeholder" in err

    def test_known_tokens_do_not_warn(self, make_masker, store, capsys):
        m = make_masker()
        store.get_or_create("PERSON", "Alice")
        m.unmask("hi <PERSON_1>")
        assert "unknown placeholder" not in capsys.readouterr().err

    def test_telemetry_counts_unknown_tokens(self, make_masker, store):
        from anon_proxy.masker import telemetry_scope
        m = make_masker()
        store.get_or_create("PERSON", "Alice")
        with telemetry_scope() as calls:
            m.unmask("<PERSON_186> and <EMAIL_99>")
        unmask_calls = [c for c in calls if c["op"] == "unmask"]
        assert unmask_calls[0]["unknown_tokens"] == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_masker.py -q -k UnknownPlaceholder`
Expected: FAIL (no warning printed, no `unknown_tokens` key).

- [ ] **Step 3: Implement**

In `anon_proxy/masker.py` (add `import sys` at top):

```python
def _find_unknown_tokens(self, text: str) -> list[str]:
    """Placeholder-shaped tokens with no store entry — the model invented
    them (hallucinated index) or the store lost them. Either way the client
    is about to receive an opaque token instead of a value; be loud."""
    seen: list[str] = []
    for m in _PLACEHOLDER_RE.finditer(text):
        tok = m.group(0)
        if self._store.original(tok) is None and tok not in seen:
            seen.append(tok)
    return seen
```

In `_sub`, after computing the substituted result (note: `_sub` returns early
when the store is empty — scan in that branch too):

```python
def _sub(self, text: str, transform: Callable[[str], str]) -> str:
    tokens = self._store.tokens()
    result = text
    if tokens:
        pattern = re.compile(
            "|".join(re.escape(t) for t in sorted(tokens, key=len, reverse=True))
        )

        def repl(m: re.Match[str]) -> str:
            original = self._store.original(m.group(0))
            return transform(original) if original is not None else m.group(0)

        result = pattern.sub(repl, text)
    unknown = self._find_unknown_tokens(result)
    for tok in unknown:
        print(
            f"warning: unmask: unknown placeholder {tok} left in response "
            f"(model may have invented it)",
            file=sys.stderr,
        )
    self._last_unknown_count = len(unknown)
    return result
```

In `unmask` and `unmask_json`, add the count to the telemetry record:
`"unknown_tokens": getattr(self, "_last_unknown_count", 0)`.

(`_last_unknown_count` is set synchronously by `_sub` immediately before the
telemetry record is appended in the same call — no cross-request state.)

- [ ] **Step 4: Full suite**

Run: `uv run pytest tests/ -q` — all pass. Streaming note: `split_at_last_open`
guarantees `unmask` only ever sees complete tokens, so no split-token false
warnings are possible; no adapter change needed.

- [ ] **Step 5: Commit**

```bash
git add anon_proxy/masker.py tests/test_masker.py
git commit -m "feat: warn when a response contains a placeholder not in the store

Weaker upstream models hallucinate placeholder indices (issue #13's
ls -<PERSON_186>); previously the token passed through silently and the
client executed garbage. Now each unknown token logs a stderr warning and
is counted in unmask telemetry."
```
