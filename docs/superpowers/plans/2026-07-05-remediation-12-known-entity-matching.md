# PR 12: Known-entity exact matching

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans or
> superpowers:subagent-driven-development. Depends on PR 11 (which renames the
> masker's detector list to `_pre_detectors`; if executing before PR 11, the
> attribute is still `self._extra`).

**Goal:** Once the store knows "Alice Smith" / "alice@company.com" from a
natural-language turn, that exact string appearing *anywhere* later — a code
comment, a JSON field, a log line, clue-less contexts where the ML model is
blind — should get the same placeholder, at regex cost.

**Architecture:** A pass-0 in `Masker.mask()` before the regex detectors:
build one compiled alternation of all stored original values (longest-first),
case-insensitive to match `_canonical`'s casefold. Rebuilt lazily, invalidated
by store growth (compare `len(store)`). **Pollution guard:** only values with
`len(value) >= min_known_entity_len` (default 6) participate — this is what
keeps a store polluted with `la`-style junk (issue #13) from masking every
occurrence of two letters. Cache interaction: mask-cache entries were computed
against a store snapshot; a value learned later won't retro-apply to a cached
text — accept this (same-turn texts are fine; history is already masked) and
document it.

## Global constraints

- See overview plan. Branch: `feat/known-entity-matching` off `main`.

---

### Task 1: KnownEntityDetector

**Files:**
- Create: `anon_proxy/known_entities.py`
- Test: `tests/test_known_entities.py`

**Interfaces:**
- Produces: `KnownEntityDetector(store: PIIStore, min_len: int = 6)` with
  `detect(text) -> list[PIIEntity]` (same protocol as RegexDetector, score 1.0,
  label = the stored entity's label).

- [ ] **Step 1: Failing tests**

```python
class TestKnownEntityDetector:
    def test_matches_stored_value_in_code_context(self, store):
        store.get_or_create("PERSON", "Alice Smith")
        d = KnownEntityDetector(store)
        ents = d.detect('git log --author="Alice Smith" | head')
        assert [(e.label, e.text) for e in ents] == [("PERSON", "Alice Smith")]

    def test_case_insensitive_matches_canonicalization(self, store):
        store.get_or_create("EMAIL", "Alice@X.com")
        d = KnownEntityDetector(store)
        ents = d.detect("send to alice@x.com now")
        assert len(ents) == 1 and ents[0].text == "alice@x.com"

    def test_short_values_excluded(self, store):
        store.get_or_create("PERSON", "la")   # issue-#13-style pollution
        d = KnownEntityDetector(store)
        assert d.detect("ls -la && la la la") == []

    def test_word_boundaries(self, store):
        store.get_or_create("PERSON", "Alice Smith")
        d = KnownEntityDetector(store)
        assert d.detect("AliceSmithson") == []   # substring of a longer word

    def test_rebuilds_after_store_growth(self, store):
        d = KnownEntityDetector(store)
        assert d.detect("Bob Jones here") == []
        store.get_or_create("PERSON", "Bob Jones")
        assert len(d.detect("Bob Jones here")) == 1
```

- [ ] **Step 2: Implement**

```python
"""Exact-match detection of values the store already knows.

The ML model needs linguistic context; a value learned once in prose then
reappearing in code/JSON/logs has none. Exact matching closes that gap at
regex cost. min_len guards against store pollution (short junk values would
otherwise mask everywhere — issue #13's 'la')."""
from __future__ import annotations

import re

from anon_proxy.mapping import PIIStore, _parse_token
from anon_proxy.privacy_filter import PIIEntity


class KnownEntityDetector:
    def __init__(self, store: PIIStore, min_len: int = 6) -> None:
        self._store = store
        self._min_len = min_len
        self._built_at = -1
        self._rx: re.Pattern[str] | None = None
        self._label_by_lower: dict[str, str] = {}

    def _rebuild(self) -> None:
        pairs = []  # (original_value, label)
        for token, value in self._store.items():
            if len(value) < self._min_len:
                continue
            parsed = _parse_token(token)
            if parsed:
                pairs.append((value, parsed[0]))
        self._label_by_lower = {v.casefold(): lab for v, lab in pairs}
        if pairs:
            alts = sorted((re.escape(v) for v, _ in pairs), key=len, reverse=True)
            self._rx = re.compile(
                r"(?<!\w)(?:" + "|".join(alts) + r")(?!\w)", re.IGNORECASE
            )
        else:
            self._rx = None
        self._built_at = len(self._store)

    def detect(self, text: str) -> list[PIIEntity]:
        if len(self._store) != self._built_at:
            self._rebuild()
        if self._rx is None or not text:
            return []
        out: list[PIIEntity] = []
        for m in self._rx.finditer(text):
            label = self._label_by_lower.get(m.group(0).casefold())
            if label is None:
                continue  # matched a casing variant of a canonical dupe — skip
            out.append(PIIEntity(label=label, text=m.group(0),
                                 start=m.start(), end=m.end(), score=1.0))
        return out
```

Note on `label is None`: two originals canonicalizing to the same casefold can
disagree; keep first-wins semantics (dict already does). Keep the lookup by
casefold of the *match*, mapping to the stored label.

- [ ] **Step 3: Commit** — `"feat: KnownEntityDetector — exact-match known store values"`.

### Task 2: Wire as pass-0 in Masker

**Files:**
- Modify: `anon_proxy/masker.py` (insert detector at the FRONT of the pre-pass
  detector list inside `__init__`: `self._pre_detectors = [KnownEntityDetector(self._store), *(extra_detectors or [])]`),
  `anon_proxy/config.py` (`min_known_entity_len: int = 6`, `0` disables),
  `anon_proxy/server.py` (thread through)
- Test: `tests/test_masker.py`

- [ ] **Step 1: Failing test**

```python
def test_learned_value_masks_later_in_code_context(self, make_masker, fake_pipeline):
    m = make_masker()
    prose = "My name is Alice Smith."
    fake_pipeline.set(prose, [span("private_person", 11, 22, word="Alice Smith")])
    assert "<PERSON_1>" in m.mask(prose)
    # Later turn: same value, zero linguistic clues, ML sees nothing.
    code = 'os.environ["OWNER"] = "Alice Smith"'
    fake_pipeline.set(code, [])
    assert m.mask(code) == 'os.environ["OWNER"] = "<PERSON_1>"'
```

- [ ] **Step 2: Implement + full suite**

Constructor change as in Files above (respect `min_known_entity_len=0` →
don't insert the detector). Watch one interaction: `_resolve_overlaps` already
arbitrates when the known-entity match and a config regex both fire —
longest-then-score wins, no new logic needed. Run full suite; existing
two-pass flow tests (`1fb4d72`) must stay green.

- [ ] **Step 3: Docs + commit**

README "How it works": one sentence — once a value is learned, exact
re-occurrences are caught anywhere, including code. Commit:
`"feat: mask known store values on exact match (pass-0)"`.
