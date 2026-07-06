# PR 11: Post-mask regex canary

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans or
> superpowers:subagent-driven-development. Depends on PR 10 (default pack).

**Goal:** Issue #1's core proposal: after masking, run the regex set over the
MASKED text. Any hit means the ML pass missed something a regex would have
caught. Modes: `warn` (log + telemetry, default) and `fix` (mask the span in
place before forwarding). This is the fail-closed principle applied to
detector quality.

**Architecture:** A final step inside `Masker.mask()` (so every call path —
adapters, walker, future callers — gets it for free). The canary reuses
`self._extra` (the regex detectors, which after PR 10 include the default
pack). Placeholder-token spans are excluded from canary hits (a regex may
match inside `<EMAIL_1>`? no — but a regex like IPV4 could match text adjacent
to tokens; use `_drop_placeholder_overlaps`, which exists). Config key
`"canary": "warn" | "fix" | "off"` (default `"warn"`).

## Global constraints

- See overview plan. Branch: `feat/post-mask-canary` off `main`.

---

### Task 1: Canary in Masker.mask

**Files:**
- Modify: `anon_proxy/masker.py` (`__init__` gains `canary: str = "warn"`;
  `mask()` gains the final pass), `anon_proxy/config.py` (`canary` key),
  `anon_proxy/server.py` (thread config through)
- Test: `tests/test_masker.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `Masker(..., canary="warn"|"fix"|"off")`. Telemetry mask records
  gain `"canary_hits": int`.

- [ ] **Step 1: Failing tests**

```python
class TestPostMaskCanary:
    def _masker(self, make_filter, store, canary):
        # Regex detector knows EMAIL; the fake ML pipeline will "miss" it.
        return Masker(filter=make_filter(), store=store,
                      extra_detectors=[RegexDetector({"EMAIL": r"[\w.]+@[\w.]+"})],
                      skip_patterns=[], canary=canary)

    def test_warn_mode_logs_and_forwards(self, make_filter, store, capsys,
                                         fake_pipeline, monkeypatch):
        m = self._masker(make_filter, store, "warn")
        # Force the regex PRE-pass to miss but the canary to catch: simulate by
        # monkeypatching the pre-pass detectors to [] AFTER construction while
        # keeping the canary list. (Split attributes: see implementation note.)
        m._pre_detectors = []
        out = m.mask("contact bob@x.com ok")
        assert "bob@x.com" in out                       # warn: forwarded
        assert "canary" in capsys.readouterr().err       # ...but loudly

    def test_fix_mode_masks_the_miss(self, make_filter, store, fake_pipeline):
        m = self._masker(make_filter, store, "fix")
        m._pre_detectors = []
        out = m.mask("contact bob@x.com ok")
        assert "bob@x.com" not in out
        assert "<EMAIL_1>" in out

    def test_off_mode_silent(self, make_filter, store, capsys, fake_pipeline):
        m = self._masker(make_filter, store, "off")
        m._pre_detectors = []
        m.mask("contact bob@x.com ok")
        assert "canary" not in capsys.readouterr().err

    def test_no_false_canary_on_clean_mask(self, make_filter, store, capsys,
                                           fake_pipeline):
        m = self._masker(make_filter, store, "warn")
        m.mask("contact bob@x.com ok")  # pre-pass catches it normally
        assert "canary" not in capsys.readouterr().err
```

- [ ] **Step 2: Implement**

Implementation note: rename `self._extra` usage sites so the pre-pass list and
canary list are the same attribute by default but separable for tests:
`self._pre_detectors = list(extra_detectors or [])` and
`self._canary_detectors = self._pre_detectors` (same list object). In
`mask()`, after the ML substitution:

```python
        if self._canary != "off" and self._canary_detectors:
            hits: list[PIIEntity] = []
            for det in self._canary_detectors:
                hits.extend(det.detect(masked))
            hits = _drop_placeholder_overlaps(_resolve_overlaps(hits), masked)
            if hits:
                for h in hits:
                    print(
                        f"warning: canary: {h.label} {h.text!r} survived masking"
                        + (" — masking now" if self._canary == "fix" else ""),
                        file=sys.stderr,
                    )
                if self._canary == "fix":
                    masked = self._substitute(masked, hits)
        # existing: self._cache_result(...) — cache stores the CANARY-FIXED
        # text; hit count goes on the telemetry record as "canary_hits".
```

Constructor: `canary: str = "warn"`, validate
`canary in ("warn", "fix", "off")` else `ValueError`. Config: add `"canary"`
to `_ALLOWED_KEYS`, string-validated the same way; `server.py` passes
`canary=cfg.canary` at both Masker construction sites (and PR 09's
`make_masker` lambda if landed).

- [ ] **Step 3: Full suite, README config docs, commit**

```bash
git commit -m "feat: post-mask regex canary (warn/fix modes)

Runs the regex pack over the already-masked text; any hit is PII the ML
pass missed (issue #1's proposal). warn logs it, fix masks it in place.
Default warn."
```
