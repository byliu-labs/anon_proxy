# PR 10: Default regex pack (clue-less PII + secrets)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans or
> superpowers:subagent-driven-development.

**Goal:** Issue #1: the ML model misses clue-less PII (bare phone number:
recall 0.32 per the model card). And for the coding-agent workload the
highest-value sensitive strings are *secrets* — deterministic, regex-friendly.
Ship a default pattern pack that runs in the existing regex-first pass.

**Architecture:** New module `anon_proxy/default_patterns.py` exporting
`DEFAULT_PATTERNS: dict[str, str]`. `Masker` construction in `server.py`
composes `RegexDetector({**DEFAULT_PATTERNS, **cfg.patterns})` — user patterns
override same-label defaults. Opt-out via config `"default_patterns": false`
(new Config field). Precision bar: every default pattern must be
high-precision; a false positive here corrupts agent commands (issue #13), so
each pattern ships with negative tests.

## Global constraints

- See overview plan. Branch: `feat/default-regex-pack` off `main`.
- No pattern lands without both positive AND negative test cases.

---

### Task 1: The pattern module

**Files:**
- Create: `anon_proxy/default_patterns.py`
- Test: `tests/test_default_patterns.py`

**Interfaces:**
- Produces: `DEFAULT_PATTERNS: dict[str, str]` (labels below are final —
  PR 11's canary and the README reference them).

- [ ] **Step 1: Failing tests** (table-driven; excerpt — cover every label)

```python
import re
import pytest
from anon_proxy.default_patterns import DEFAULT_PATTERNS

POSITIVE = [
    ("EMAIL", "alice.smith+tag@sub.example.co.uk"),
    ("PHONE", "+1 (415) 555-2671"),
    ("PHONE", "415-555-2671"),
    ("SSN", "078-05-1120"),
    ("IPV4", "10.42.4.43"),
    ("CREDIT_CARD", "4111 1111 1111 1111"),
    ("AWS_ACCESS_KEY", "AKIAIOSFODNN7EXAMPLE"),
    ("GITHUB_TOKEN", "ghp_16CharactersOfEntropy0123456789abcd"),
    ("JWT", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
    ("PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----"),
]
NEGATIVE = [
    ("PHONE", "torch==2.11.0"),          # version strings
    ("PHONE", "1234"),                   # too short
    ("SSN", "127-0-1"),
    ("IPV4", "999.999.999.999"),         # not a valid octet
    ("CREDIT_CARD", "1234 5678"),
    ("EMAIL", "not-an-email@"),
    ("GITHUB_TOKEN", "ghp_short"),
]

@pytest.mark.parametrize("label,text", POSITIVE)
def test_pattern_matches(label, text):
    assert re.search(DEFAULT_PATTERNS[label], text), (label, text)

@pytest.mark.parametrize("label,text", NEGATIVE)
def test_pattern_rejects(label, text):
    assert not re.search(DEFAULT_PATTERNS[label], text), (label, text)
```

- [ ] **Step 2: Implement**

```python
"""Default regex detectors: clue-less PII the ML model misses (model card
§7.5.1 — bare phone recall 0.32) plus secrets, which dominate the sensitive
strings in coding-agent traffic and are deterministic. Precision bar is HIGH:
a false positive corrupts agent commands (issue #13), so patterns favor
anchored, structured shapes over broad ones."""

DEFAULT_PATTERNS: dict[str, str] = {
    "EMAIL": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    # 10+ digit sequences with phone punctuation/spacing; requires separators
    # or +CC prefix so versions/IDs don't match.
    "PHONE": r"(?<![\w.=/])(?:\+\d{1,3}[ .-]?)?(?:\(\d{2,4}\)[ .-]?)?\d{3}[ .-]\d{3,4}[ .-]?\d{0,4}(?![\w.-])",
    "SSN": r"\b\d{3}-\d{2}-\d{4}\b",
    "IPV4": r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b",
    "CREDIT_CARD": r"\b(?:\d[ -]?){13,19}\b",  # tighten with Luhn note below
    "AWS_ACCESS_KEY": r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    "GITHUB_TOKEN": r"\bgh[pousr]_[A-Za-z0-9]{36,}\b",
    "JWT": r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",
    "PRIVATE_KEY": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "SLACK_TOKEN": r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b",
}
```

Iterate patterns against the tests until green — the tests are the spec, the
literal regexes above are starting points. CREDIT_CARD as written will
overmatch plain 13–19 digit runs; either add a Luhn check hook (RegexDetector
has no post-filter — keep regex-only and require separators: choose based on
the negative tests) — decide in code review, both are defensible, document the
choice in the module docstring.

- [ ] **Step 3: Commit** — `"feat: default regex pack for clue-less PII and secrets"`.

### Task 2: Wire as defaults with opt-out

**Files:**
- Modify: `anon_proxy/config.py` (`Config.default_patterns: bool = True`,
  `_ALLOWED_KEYS` + parse), `anon_proxy/server.py` (detector construction)
- Test: `tests/test_config.py`, `tests/test_server.py`

**Interfaces:**
- Produces: effective patterns = `{**DEFAULT_PATTERNS, **cfg.patterns}` when
  `cfg.default_patterns` else `cfg.patterns`.

- [ ] **Step 1: Failing tests**

```python
def test_default_patterns_flag_parses(tmp_path):
    p = tmp_path / "c.json"; p.write_text('{"default_patterns": false}')
    assert load_config(p).default_patterns is False

def test_default_patterns_default_true(tmp_path):
    p = tmp_path / "c.json"; p.write_text('{}')
    assert load_config(p).default_patterns is True
```

Plus a server-level test asserting the built Masker's detector list includes
the defaults (follow however test_server currently introspects `build_app`
wiring; if it doesn't, test via `main()`-level factoring — extract a
`_effective_patterns(cfg) -> dict` helper in server.py and unit-test that).

- [ ] **Step 2: Implement**

`config.py`: add field + `_bool` parse (same pattern as `system_inject`).
`server.py` in `main()`:

```python
    effective_patterns = (
        {**DEFAULT_PATTERNS, **cfg.patterns} if cfg.default_patterns
        else dict(cfg.patterns)
    )
    extra_detectors = []
    if effective_patterns:
        extra_detectors.append(RegexDetector(effective_patterns))
```

Note the Masker-construction conditional at `server.py:925-934` must now
build a Masker whenever `effective_patterns` is non-empty (it always is with
defaults on) — simplify: always construct the Masker explicitly and delete the
`else None` branch (good taste: one path, no conditional wiring).

- [ ] **Step 3: Full suite + `--collect-only` check, README config-section
  update, commit** — `"feat: enable default regex pack by default (config opt-out)"`.

### Task 3: Replay evidence (PR handoff gate)

- [ ] `uv run python test_filter.py "442 222 47571"` → must now mask (this was
  issue #1's headline repro; it needs the server-side composition, so verify
  via a masker-level scriptlet or the proxy with `--debug`, and paste output
  in the PR).
- [ ] Replay a captured session (`bench_replay.py`) and diff the store: report
  new label counts (evidence the pack fires on real traffic without exploding).
