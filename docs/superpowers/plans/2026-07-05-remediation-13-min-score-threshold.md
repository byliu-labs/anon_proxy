# PR 13: `min_score` threshold for ML detections — GATED ON EVIDENCE

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans.
> **Do not start this PR until the evidence step below says it's worth it.**

**Goal:** Give deployments a precision knob: drop ML detections below a
confidence score. Motivated by issue #13's code over-masking — but issue #1's
data shows real hits also score ~1.0, so it is NOT yet known whether junk
detections are separable by score.

**Evidence gate (do this first, ~30 min):**
- [ ] Take a real capture with known pollution (the 186-PERSON session).
  Replay detection over its pre-mask bodies and histogram scores for (a) spans
  you'd judge junk (short/code-context), (b) plausible hits.
  `uv run python - <<'EOF'` scriptlet: load capture.jsonl, run
  `PrivacyFilter().detect_raw(text)` per turn, print `score, word` sorted.
- [ ] If junk and real scores overlap heavily (both ~1.0) → **close this plan
  as won't-do**, note the finding on issue #13, and rely on PRs 10/12/14 +
  `ignore_labels` instead. If separable → proceed.

**Architecture (if proceeding):** `Config.min_score: float = 0.0` (0 = today's
behavior, no silent default change). Filter in `Masker.mask()` where
`ignore_labels` already filters ML entities — same list comprehension site,
one more condition.

## Global constraints

- See overview plan. Branch: `feat/min-score` off `main`.

---

### Task 1: Config + filter

**Files:**
- Modify: `anon_proxy/config.py` (field, `_ALLOWED_KEYS`, float validation:
  must be `0.0 <= v <= 1.0`), `anon_proxy/masker.py` (constructor
  `min_score: float = 0.0`; filter), `anon_proxy/server.py` (thread through)
- Test: `tests/test_masker.py`, `tests/test_config.py`

- [ ] **Step 1: Failing tests**

```python
def test_min_score_drops_low_confidence_ml_hits(self, make_masker, fake_pipeline):
    m = make_masker(min_score=0.8)   # extend the conftest factory kwarg
    text = "maybe Alice maybe not"
    fake_pipeline.set(text, [span("private_person", 6, 11, word="Alice", score=0.42)])
    assert m.mask(text) == text      # below threshold → not masked

def test_min_score_keeps_high_confidence(self, make_masker, fake_pipeline):
    m = make_masker(min_score=0.8)
    text = "I am Alice."
    fake_pipeline.set(text, [span("private_person", 5, 10, word="Alice", score=0.99)])
    assert "<PERSON_1>" in m.mask(text)

def test_min_score_never_applies_to_regex_hits(self, make_masker):
    m = make_masker(min_score=0.99,
                    extra_detectors=[RegexDetector({"SSN": r"\d{3}-\d{2}-\d{4}"})])
    # regex detectors emit score=1.0 but conceptually bypass the ML threshold
    assert "<SSN_1>" in m.mask("ssn 078-05-1120")

def test_config_min_score_bounds(tmp_path):
    p = tmp_path / "c.json"; p.write_text('{"min_score": 1.5}')
    with pytest.raises(ValueError):
        load_config(p)
```

- [ ] **Step 2: Implement**

In `Masker.mask()`, the existing ML-entity filter block becomes:

```python
        if self._ignore_labels or self._min_score:
            ml_entities = [
                e for e in ml_entities
                if normalize_label(e.label) not in self._ignore_labels
                and e.score >= self._min_score
            ]
```

Config validation mirrors `_bool` (add `_float01`). conftest `make_masker`
gains a `min_score=0.0` passthrough kwarg.

- [ ] **Step 3: Full suite, README config docs (include the measured
  histogram from the evidence gate as the tuning guidance), commit** —
  `"feat: min_score config threshold for ML detections"`.
