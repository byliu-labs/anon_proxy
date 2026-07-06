# PR 05: Batched chunk inference + larger default chunks

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans or
> superpowers:subagent-driven-development. Depends on PR 04 (`_infer_lock`).

**Goal:** A 100KB tool result is currently 67 sequential forward passes
(`privacy_filter.py:84-99` loops `self._pipe(chunk)` per chunk). Batch all
chunks into one pipeline call and raise the 1500-char default (a BERT-era
assumption; see issue #1 discussion of the model's real context length).

**Architecture:** `_split_chunks` already returns all chunks up front; pass the
list to the pipeline (`self._pipe(texts, batch_size=N)` returns list-of-lists —
`tests/conftest.py` FakePipeline already models both shapes). New constructor
param `batch_size` (default 8) and module constant `DEFAULT_CHUNK_SIZE = 6000`
used by both `PrivacyFilter` and the server's argparse default, so the "did the
user override it" check in `server.py:897` compares against one source of truth.

**Validation:** `bench_replay.py` on a real capture, before vs after — this PR
is the main lever for the 1.5× e2e target. Record numbers in the PR description.

## Global constraints

- See overview plan. Branch: `perf/batched-inference` off `main`.
- 6000 chars ≈ 1500 tokens; if replay shows VRAM pressure on a 4GB GPU,
  fall back to 4000 and note it — the constant is the knob.

---

### Task 1: Batch the pipeline call

**Files:**
- Modify: `anon_proxy/privacy_filter.py` (`__init__`, `detect`)
- Test: `tests/test_privacy_filter.py`

**Interfaces:**
- Produces: `PrivacyFilter(..., batch_size: int = 8)`;
  `detect()` behavior identical (same entities, same offsets).

- [ ] **Step 1: Failing test — one pipeline call for a multi-chunk text**

```python
def test_multichunk_text_is_one_batched_pipeline_call(make_filter, fake_pipeline):
    f = make_filter(chunk_size=10)
    text = "aaaa bbbb cccc dddd"          # splits into multiple chunks
    entities = f.detect(text)
    assert entities == []
    # exactly one pipeline invocation, and it received a list of chunks
    assert len(fake_pipeline.calls) == 1
    assert isinstance(fake_pipeline.calls[0], list)
    assert "".join(fake_pipeline.calls[0]) == text
```

Also add an offset-correctness test: register a span on the *second* chunk via
`fake_pipeline.set(<second chunk text>, [span(...)])` and assert the returned
entity's `start`/`end` carry the chunk offset (mirrors the existing per-chunk
offset test — keep that one passing too).

Run: `uv run pytest tests/test_privacy_filter.py -q -k batched` → FAIL
(today: one call per chunk, each a str).

- [ ] **Step 2: Implement**

```python
DEFAULT_CHUNK_SIZE = 6000  # ~1500 tokens; well within the model's context.
                           # 1500 was a BERT-512 assumption (see issue #1).

class PrivacyFilter:
    def __init__(self, *, aggregation_strategy="simple", merge_adjacent=True,
                 merge_gap_allowed=None, chunk_size=DEFAULT_CHUNK_SIZE,
                 batch_size: int = 8, device=None) -> None:
        ...existing...
        self._batch_size = batch_size

    def detect(self, text: str) -> list[PIIEntity]:
        if not text.strip():
            return []
        chunks = _split_chunks(text, self._chunk_size)
        texts = [c for _, c in chunks]
        with self._infer_lock:
            all_results = self._pipe(texts, batch_size=self._batch_size)
        entities: list[PIIEntity] = []
        for (offset, chunk), results in zip(chunks, all_results):
            for r in results:
                e = _to_entity(r, chunk)
                if e is None:
                    continue
                entities.append(PIIEntity(label=e.label, text=e.text,
                                          start=e.start + offset,
                                          end=e.end + offset, score=e.score))
        if self._merge_adjacent:
            entities = _merge_adjacent_entities(entities, text, self._gap_allowed)
        return entities
```

Note: a single-element list still goes through the list path — one code path,
no special case for short texts.

- [ ] **Step 3: Full suite, commit**

`uv run pytest tests/ -q` → pass.
Commit: `"perf: batch chunk inference into one pipeline call"`.

### Task 2: Single source of truth for the chunk-size default + CLI batch-size

**Files:**
- Modify: `anon_proxy/server.py:830-835` (argparse `--chunk-size`), `:897`
  (the `args.chunk_size != 1500` comparison), new `--batch-size` flag,
  `PrivacyFilter(...)` construction.
- Test: `tests/test_server.py` (flag plumbing, if the existing suite covers
  argparse defaults; otherwise cover via `build_app` path only and note it).

- [ ] **Step 1: Implement**

```python
from anon_proxy.privacy_filter import DEFAULT_CHUNK_SIZE, PrivacyFilter
...
parser.add_argument("--chunk-size", type=int,
    default=int(os.environ.get("ANON_PROXY_CHUNK_SIZE", str(DEFAULT_CHUNK_SIZE))), ...)
parser.add_argument("--batch-size", type=int,
    default=int(os.environ.get("ANON_PROXY_BATCH_SIZE", "8")),
    help="Batch size for model inference over chunks (default: 8).")
...
if cfg.merge_gap or args.chunk_size != DEFAULT_CHUNK_SIZE or args.backend != "auto" or args.batch_size != 8:
    pf = PrivacyFilter(merge_gap_allowed=cfg.merge_gap or None,
                       chunk_size=args.chunk_size, batch_size=args.batch_size,
                       device=device)
```

Update README flag table (`--chunk-size` default 6000, new `--batch-size`).

- [ ] **Step 2: Full suite, commit**

`uv run pytest tests/ -q` → pass.
Commit: `"perf: raise default chunk size to 6000, add --batch-size"`.

### Task 3: Benchmark evidence (PR handoff gate)

- [ ] Run `uv run python bench_replay.py --capture <real capture.jsonl>` on
  `main` and on this branch, same machine. Paste both outputs in the PR
  description. Expected: multi-chunk turns (big tool results) drop by roughly
  the old chunk-count factor; if not, investigate before opening the PR.
- [ ] Live 1.5× check: time an identical Claude Code prompt through proxy vs
  direct (3 runs each, compare medians — LLM variance is real, note it).
