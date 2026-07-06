# PR 01: Stop skipping `<system-reminder>` blocks

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans or
> superpowers:subagent-driven-development. Steps use checkbox syntax.

**Goal:** Remove the default skip pattern so Claude Code system-reminder content
(userEmail, CLAUDE.md text) is masked like everything else.

**Architecture:** `_SKIP_MASK_PATTERNS` in `masker.py` becomes an empty list. The
`skip_patterns` constructor parameter stays (tested, harmless, and a future
exact-string allowlist could use it) — only the dangerous default dies. Perf
regression on repeated boilerplate is absorbed by the existing block cache
(PRs 04/05 handle first-sight cost).

**Why (context for the PR description):** any text where a line starts with
`<system-reminder>` is currently forwarded 100% unmasked. Claude Code puts the
user's email and CLAUDE.md contents inside those blocks, and appends reminder
lines to tool results — so whole file reads can skip masking. Issue #6's log
shows a skipped block containing `# userEmail`.

## Global constraints

- See overview plan. Branch: `fix/mask-system-reminders` off `main`.

---

### Task 1: Default masker masks system-reminder text

**Files:**
- Modify: `anon_proxy/masker.py:40-46` (`_SKIP_MASK_PATTERNS`)
- Test: `tests/test_masker.py:415-480` (skip_patterns section)

**Interfaces:**
- Produces: `Masker()` default behavior — no text is exempt from detection.
  `skip_patterns` param unchanged (`list[re.Pattern] | None`, default `None`
  → now means "no skips").

- [ ] **Step 1: Rewrite the default-skip tests to assert masking happens**

In `tests/test_masker.py`, the tests around lines 420–436 currently assert the
default patterns *bypass* masking. Invert them:

```python
class TestDefaultSkipPatterns:
    def test_system_reminder_text_is_masked_by_default(
        self, make_filter, fake_pipeline, store
    ):
        # Default skip_patterns must NOT exempt system-reminder blocks:
        # Claude Code puts real PII (userEmail, CLAUDE.md) inside them.
        m = Masker(filter=make_filter(), store=store)  # default skip_patterns
        text = "<system-reminder>\n# userEmail\nalice@example.com\n</system-reminder>"
        fake_pipeline.set(text, [span("private_email", 32, 49, word="alice@example.com")])
        masked = m.mask(text)
        assert "alice@example.com" not in masked
        assert "<EMAIL_1>" in masked

    def test_indented_system_reminder_also_masked(
        self, make_filter, fake_pipeline, store
    ):
        m = Masker(filter=make_filter(), store=store)
        text = "   <system-reminder>x</system-reminder>"
        fake_pipeline.set(text, [])
        assert m.mask(text) == text  # no PII → unchanged, but pipeline WAS consulted
        assert fake_pipeline.calls, "detector must run on system-reminder text"
```

Check the exact offsets by running the test — adjust `span(...)` start/end so
`text[start:end] == "alice@example.com"`. Keep the explicit-`skip_patterns`
tests at lines 444–479 as-is (the mechanism still works when opted into).

- [ ] **Step 2: Run to verify the new tests fail**

Run: `uv run pytest tests/test_masker.py -q -k "system_reminder or DefaultSkip"`
Expected: new tests FAIL (text passes through unmasked; `fake_pipeline.calls` empty).

- [ ] **Step 3: Empty the default pattern list**

In `anon_proxy/masker.py` replace lines 40–46 with:

```python
# No default skip patterns. Skipping content by pattern is a fail-open hole:
# Claude Code's <system-reminder> blocks carry real PII (userEmail, CLAUDE.md)
# and reminder lines get appended to tool results, exempting whole file reads.
# Perf for repeated boilerplate comes from the block/content caches instead.
# `skip_patterns` remains as an explicit opt-in for callers who accept the risk.
_SKIP_MASK_PATTERNS: list[re.Pattern] = []
```

- [ ] **Step 4: Full suite**

Run: `uv run pytest tests/ -q`
Expected: all pass (fix any other test that assumed the old default).

- [ ] **Step 5: Update docs**

- `README.md` "What gets protected" section: it now tells the truth; add
  "including Claude Code system-reminder blocks".
- `SECURITY.md` known-limitations: no change needed, but grep for
  "system-reminder" to be sure nothing documents the old skip.

- [ ] **Step 6: Commit**

```bash
git add anon_proxy/masker.py tests/test_masker.py README.md
git commit -m "fix: mask <system-reminder> blocks instead of skipping them

The default skip pattern forwarded any block containing a system-reminder
line completely unmasked. Claude Code places userEmail and CLAUDE.md
contents in those blocks and appends reminder lines to tool results, so
this exempted exactly the content that always carries PII (visible in
issue #6's debug log). Perf for repeated boilerplate is handled by the
block cache; skip_patterns stays as an explicit opt-in only."
```
