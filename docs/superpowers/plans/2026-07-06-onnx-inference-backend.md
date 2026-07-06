# Fast Inference Backend (ONNX) + `--backend mlx` Crash Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut per-turn masking latency ≥30% by running the model's upstream-shipped quantized ONNX exports through ONNX Runtime, and fix the `--backend mlx` flag that currently crashes the server at startup.

**Architecture:** `PrivacyFilter` gains a `backend` parameter. `torch` (default) keeps the existing HF pipeline byte-for-byte. `onnx*` backends load the pre-quantized ONNX graphs that `openai/privacy-filter` already ships (`onnx/model_q4f16.onnx` ≈ 0.77 GB vs 2.6 GB bf16 safetensors) via `optimum.onnxruntime`, wrapped in the SAME HF pipeline object — so chunking, batching, adjacency merge, and BIOES aggregation code paths are untouched. A golden parity suite gates any non-torch backend; a benchmark gate decides whether the README recommends it.

**Tech Stack:** `optimum[onnxruntime]` as an optional extra (`anon-proxy[onnx]`), existing `transformers` pipeline, pytest.

## Why ONNX and not MLX (decision record)

The bench (see `2026-07-06-landing-plan-kevin-migration.md` §Perf validation) showed masking adds ~6.5s per turn of new content on CPU and that MPS is 1.5× *slower* than CPU (per-sequence-length kernel recompiles). `--backend mlx` is advertised in `--help` but there is no MLX implementation — the string `"mlx"` is passed straight into `pipeline(device=...)` and torch dies with `RuntimeError: unknown device string 'mlx'` (server.py, `device = None if args.backend == "auto" else args.backend`).

Facts that decide the direction (verified against the local HF cache, snapshot `7ffa9a0`):
- The architecture is **custom**: `model_type: openai_privacy_filter`, 8 layers, hidden 640, sliding-window attention (window 128), BIOES tag scheme, plus a `viterbi_calibration.json` decode artifact. A from-scratch MLX port means reimplementing a custom encoder + calibrated decoding — weeks of risk for one platform.
- The repo **already ships ONNX exports**: `onnx/model.onnx` (fp32, ~5.3 GB), `onnx/model_fp16.onnx` (~2.6 GB), `onnx/model_quantized.onnx` (int8, ~1.5 GB), `onnx/model_q4.onnx` (~0.88 GB), `onnx/model_q4f16.onnx` (~0.77 GB). These are upstream-validated artifacts; int8/q4 quantization is where CPU inference typically gains 2–4×.
- ONNX Runtime is cross-platform (helps the k8s multi-user deployment too, not just macOS). MLX would help exactly one platform.

MLX stays a possible future workstream ONLY if the ONNX CPU numbers miss the bench gate; the CoreML execution provider (`ORTModel(..., provider="CoreMLExecutionProvider")`) is the cheaper Apple-accelerator experiment to try before any MLX port.

## Global Constraints

- Python `>=3.10`; `uv` only (`uv add`, `uv run pytest`) — never pip/poetry.
- `torch` backend behavior must be byte-identical after the refactor (default unchanged).
- ONNX dependencies must be OPTIONAL — base install must not grow; guard imports with a clear install hint.
- Tests requiring the real model are opt-in via `ANON_PROXY_LIVE_TESTS=1` (multi-GB downloads; CI must stay green without them).
- Every task ends with `uv run pytest tests/ -q`, `uv run ruff check .`, `uv run ruff format --check .` green (the exact CI jobs).
- No commits to main — branch per task, PR per deliverable.
- Base the work on `land/integration` (or Kevin's main once the stack has landed there).

---

### Task 1: Fail fast — remove the crashing `mlx` backend (standalone bug-fix PR)

`--backend mlx` and `--mlx-weights-cache` advertise a backend that does not exist. Anyone who tries it gets a torch traceback at startup. This task is shippable alone as a small upstream PR (it is also the fix for the public issue we file — draft text at the bottom of this plan).

**Files:**
- Modify: `anon_proxy/server.py` (the `--backend` and `--mlx-weights-cache` `add_argument` calls, and the startup banner's `backend_display`)
- Modify: `README.md` (remove any `mlx` mention)
- Test: `tests/test_server.py`

**Interfaces:**
- Produces: `--backend` choices become exactly `["auto", "cpu", "mps"]` (Task 4 re-extends them). `--mlx-weights-cache` is deleted.

- [ ] **Step 1: Write the failing test**

```python
class TestBackendFlag:
    def test_mlx_backend_rejected(self, capsys):
        """--backend mlx was advertised but never implemented (crashed at
        startup); argparse must reject it with a clear choices error."""
        with pytest.raises(SystemExit) as exc:
            _parse_args(["--backend", "mlx"])
        assert exc.value.code == 2
        assert "invalid choice: 'mlx'" in capsys.readouterr().err

    def test_mlx_weights_cache_flag_removed(self):
        with pytest.raises(SystemExit):
            _parse_args(["--mlx-weights-cache", "/tmp/x"])
```

Adjust `_parse_args` to whatever helper `tests/test_server.py` already uses for flag tests (there are existing arg-parsing tests to copy the import pattern from). If argument parsing is inline in `main()`, extract `def _parse_args(argv: list[str] | None = None)` first — that extraction belongs in this task.

- [ ] **Step 2: Run it, verify it fails** — `uv run pytest tests/test_server.py::TestBackendFlag -v` → FAIL (mlx currently accepted).

- [ ] **Step 3: Implement** — in `server.py`:

```python
    parser.add_argument(
        "--backend",
        default=os.environ.get("ANON_PROXY_BACKEND", "auto"),
        choices=["auto", "cpu", "mps"],
        help="PII detection device (default: auto-detect).",
    )
```

Delete the entire `--mlx-weights-cache` `add_argument` block. Grep for leftovers: `grep -rn "mlx" anon_proxy/ README.md` must return nothing.

- [ ] **Step 4: Run tests** — `uv run pytest tests/ -q` → all pass. `uv run ruff check . && uv run ruff format --check .` → clean.

- [ ] **Step 5: Commit**

```bash
git add anon_proxy/server.py tests/test_server.py README.md
git commit -m "fix: reject --backend mlx instead of crashing at startup

The flag advertised an MLX backend that was never implemented; the raw
string reached torch as a device and raised RuntimeError. Remove it (and
--mlx-weights-cache) until a real fast backend exists."
```

---

### Task 2: `backend` parameter on PrivacyFilter + optional `onnx` extra

**Files:**
- Modify: `anon_proxy/privacy_filter.py` (`PrivacyFilter.__init__`)
- Modify: `pyproject.toml` (optional-dependencies)
- Test: `tests/test_privacy_filter.py`

**Interfaces:**
- Produces: `PrivacyFilter(backend: str = "torch", device: int | str | None = None, ...)`. Valid backends: `"torch"`, `"onnx"`, `"onnx-int8"`, `"onnx-q4f16"`. `device` applies only to `"torch"` (ValueError if combined with an onnx backend). Module constant `ONNX_FILES: dict[str, str]` maps backend name → repo file path.
- Consumes: nothing new; the constructed `self._pipe` must remain callable as `self._pipe(texts, batch_size=N)` so `detect()` is untouched.

- [ ] **Step 1: Add the extra to pyproject.toml**

```toml
[project.optional-dependencies]
onnx = [
    "optimum[onnxruntime]>=1.24",
]
```

Run `uv sync --extra onnx` once locally to lock it (do NOT make it a base dependency).

- [ ] **Step 2: Write the failing tests** (no model download needed — these test validation and the import guard):

```python
class TestBackendParam:
    def test_unknown_backend_rejected(self):
        with pytest.raises(ValueError, match="backend must be one of"):
            PrivacyFilter(backend="mlx")

    def test_device_incompatible_with_onnx(self):
        with pytest.raises(ValueError, match="device is only valid"):
            PrivacyFilter(backend="onnx-q4f16", device="cpu")

    def test_onnx_missing_extra_message(self, monkeypatch):
        """Without optimum installed the error must say how to install it."""
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *a, **kw):
            if name.startswith("optimum"):
                raise ImportError(name)
            return real_import(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(RuntimeError, match=r"uv sync --extra onnx"):
            PrivacyFilter(backend="onnx-q4f16")
```

Note: if `PrivacyFilter.__init__` unconditionally builds the torch pipeline today, these tests will also download the model. Structure `__init__` so validation and the backend dispatch happen BEFORE any pipeline construction (see Step 4) and monkeypatch `pipeline` in existing tests if they don't already.

- [ ] **Step 3: Run, verify fail** — `uv run pytest tests/test_privacy_filter.py::TestBackendParam -v` → FAIL.

- [ ] **Step 4: Implement** in `privacy_filter.py`:

```python
BACKENDS = ("torch", "onnx", "onnx-int8", "onnx-q4f16")

# Upstream ships these pre-exported graphs in the model repo; we load, never
# convert. q4f16 is the smallest (~0.77 GB) and the primary candidate.
ONNX_FILES: dict[str, str] = {
    "onnx": "onnx/model.onnx",
    "onnx-int8": "onnx/model_quantized.onnx",
    "onnx-q4f16": "onnx/model_q4f16.onnx",
}
```

In `__init__`, replace the unconditional `self._pipe = pipeline(...)` with:

```python
        if backend not in BACKENDS:
            raise ValueError(f"backend must be one of {BACKENDS}, got {backend!r}")
        if backend != "torch" and device is not None:
            raise ValueError("device is only valid with the torch backend")
        if backend == "torch":
            self._pipe = pipeline(
                task="token-classification",
                model=self.MODEL_ID,
                aggregation_strategy=aggregation_strategy,
                device=device,
            )
        else:
            self._pipe = _build_onnx_pipeline(
                self.MODEL_ID, backend, aggregation_strategy
            )
```

Module-level helper:

```python
def _build_onnx_pipeline(model_id: str, backend: str, aggregation_strategy: str):
    try:
        from optimum.onnxruntime import ORTModelForTokenClassification
    except ImportError as e:
        raise RuntimeError(
            f"backend {backend!r} requires the onnx extra: uv sync --extra onnx"
        ) from e
    from transformers import AutoTokenizer

    model = ORTModelForTokenClassification.from_pretrained(
        model_id, file_name=ONNX_FILES[backend]
    )
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    return pipeline(
        task="token-classification",
        model=model,
        tokenizer=tokenizer,
        aggregation_strategy=aggregation_strategy,
    )
```

- [ ] **Step 5: SPIKE GATE (decides the rest of the task).** Run one real load:

```bash
uv run python -c "
from anon_proxy.privacy_filter import PrivacyFilter
pf = PrivacyFilter(backend='onnx-q4f16')
print(pf.detect('My name is Alice Smith, reach me at alice.smith@example.com.'))
"
```

Expected: PERSON + EMAIL entities, same spans as the torch backend. **Known risk:** `model_type: openai_privacy_filter` is a custom architecture; `optimum`'s `ORTModelForTokenClassification` may refuse it (it consults `AutoConfig`, which resolves fine since the torch pipeline works — but optimum has its own arch allowlists in some code paths). **If optimum refuses**, fall back to a raw `onnxruntime.InferenceSession` wrapper — replace `_build_onnx_pipeline`'s body with construction of this class, which mimics the only pipeline surface `detect()` uses (`__call__(texts, batch_size=N)` → list-of-list-of span dicts with `entity_group/score/start/end`):

```python
class _OrtTokenClassifier:
    """Minimal ONNX Runtime replacement for the HF pipeline call surface.

    Only used when optimum cannot wrap the custom architecture. Implements
    aggregation equivalent to HF 'simple': argmax per token, strip the
    B-/I-/E-/S- prefix, merge consecutive tokens sharing a base label, span
    boundaries from the fast tokenizer's offset mapping, score = mean of
    member-token softmax maxima.
    """

    def __init__(self, model_path: str, tokenizer, id2label: dict[int, str]) -> None:
        import onnxruntime as ort

        self._sess = ort.InferenceSession(
            model_path, providers=["CPUExecutionProvider"]
        )
        self._tok = tokenizer
        self._id2label = id2label

    def __call__(self, texts, batch_size: int = 8):
        if isinstance(texts, str):
            return self._one_batch([texts])[0]
        out = []
        for i in range(0, len(texts), batch_size):
            out.extend(self._one_batch(texts[i : i + batch_size]))
        return out

    def _one_batch(self, texts: list[str]) -> list[list[dict]]:
        import numpy as np

        enc = self._tok(
            texts,
            return_offsets_mapping=True,
            return_tensors="np",
            padding=True,
            truncation=False,
        )
        feeds = {
            k: v
            for k, v in enc.items()
            if k in {i.name for i in self._sess.get_inputs()}
        }
        (logits,) = self._sess.run(None, feeds)
        # softmax over labels
        e = np.exp(logits - logits.max(axis=-1, keepdims=True))
        probs = e / e.sum(axis=-1, keepdims=True)
        results = []
        for b, text in enumerate(texts):
            spans: list[dict] = []
            current: dict | None = None
            scores: list[float] = []
            for t, (start, end) in enumerate(enc["offset_mapping"][b]):
                if start == end:  # special/padding token
                    continue
                label_id = int(probs[b, t].argmax())
                tag = self._id2label[label_id]
                if tag == "O":
                    current = _flush(spans, current, scores)
                    continue
                base = tag.split("-", 1)[1]
                if current is not None and current["entity_group"] == base:
                    current["end"] = int(end)
                    scores.append(float(probs[b, t, label_id]))
                else:
                    current = _flush(spans, current, scores)
                    current = {
                        "entity_group": base,
                        "start": int(start),
                        "end": int(end),
                    }
                    scores = [float(probs[b, t, label_id])]
            _flush(spans, current, scores)
            for s in spans:
                s["word"] = text[s["start"] : s["end"]]
            results.append(spans)
        return results


def _flush(spans: list[dict], current: dict | None, scores: list[float]):
    if current is not None:
        current["score"] = sum(scores) / len(scores)
        spans.append(current)
    return None
```

Caveats to verify during the spike if the fallback is needed: the exact input names the graph expects (`self._sess.get_inputs()`), and whether long inputs need the model's sliding-window handling (our chunker already caps at 6000 chars ≈ 1500 tokens, well under `initial_context_length: 4096`, so no).

- [ ] **Step 6: Run tests** — `uv run pytest tests/ -q && uv run ruff check . && uv run ruff format --check .` → green.

- [ ] **Step 7: Commit**

```bash
git add anon_proxy/privacy_filter.py pyproject.toml uv.lock tests/test_privacy_filter.py
git commit -m "feat: onnx inference backends for PrivacyFilter (optional extra)

Loads the pre-quantized ONNX graphs shipped in the openai/privacy-filter
repo through optimum.onnxruntime, behind the same HF pipeline surface —
chunking, batching and BIOES aggregation are unchanged. torch stays the
default; onnx deps are opt-in via 'uv sync --extra onnx'."
```

---

### Task 3: Golden parity suite (gates every non-torch backend)

A quantized graph that silently misses entities is a privacy regression, not a perf win. This suite is the acceptance bar: **an onnx backend may not miss any entity the torch backend finds on the golden set.**

**Files:**
- Create: `tests/test_backend_parity.py`

**Interfaces:**
- Consumes: `PrivacyFilter(backend=...)` from Task 2.
- Produces: the golden text list `GOLDEN` (reused by the benchmark in Task 5).

- [ ] **Step 1: Write the suite** (opt-in — real model, multi-GB):

```python
"""Parity gate: onnx backends vs the torch reference, real model.

Opt-in (downloads gigabytes, minutes of runtime):
    ANON_PROXY_LIVE_TESTS=1 uv run pytest tests/test_backend_parity.py -v
"""

import os

import pytest

from anon_proxy.privacy_filter import PrivacyFilter

pytestmark = pytest.mark.skipif(
    os.environ.get("ANON_PROXY_LIVE_TESTS") != "1",
    reason="live-model test; set ANON_PROXY_LIVE_TESTS=1",
)

# One entry per failure mode we care about: every label the store CLI can
# print, multi-word merges, chunk-boundary adjacency, code context, unicode,
# PII-free text (false-positive check).
GOLDEN = [
    "My name is Alice Smith, reach me at alice.smith@example.com.",
    "Call Jean-Luc O'Neil at 555-867-5309 before Friday.",
    "Ship it to 123 Main St., Apt #4, Springfield IL 62704.",
    "Meeting moved to Jan 3, 2026 with Dr. Maria Gonzalez-Ruiz.",
    "Acme Corp & Sons acquired Globex; contact legal@acme-corp.example.",
    "SSH key fingerprint aside, my token is sk-not-a-real-secret-value-42.",
    "def notify(user):\n    send(to='bob.jones@example.org', by=user.phone)\n",
    "账户持有人：王小明，电话 +86 138 0013 8000。",
    "The quarterly report shows no anomalies across all regions.",  # no PII
    "Visit https://intranet.example.com/profile/alice-smith for details.",
    # ~7KB text forcing two chunks, PII placed to straddle the 6000-char
    # boundary — build it, don't paste it:
    ("x" * 5990) + " Alice Smith lives at 9 Elm Road. " + ("y" * 1000),
]


@pytest.fixture(scope="module")
def torch_pf():
    return PrivacyFilter(backend="torch")


@pytest.mark.parametrize("backend", ["onnx", "onnx-int8", "onnx-q4f16"])
def test_no_missed_entities_vs_torch(backend, torch_pf):
    onnx_pf = PrivacyFilter(backend=backend)
    misses, extras = [], []
    for text in GOLDEN:
        ref = {(e.label, e.text) for e in torch_pf.detect(text)}
        got = {(e.label, e.text) for e in onnx_pf.detect(text)}
        misses += [(text[:40], m) for m in ref - got]
        extras += [(text[:40], x) for x in got - ref]
    # extras are logged (over-masking is safe, just noisy); misses FAIL.
    if extras:
        print(f"[{backend}] over-detections vs torch: {extras}")
    assert not misses, f"[{backend}] MISSED entities vs torch: {misses}"
```

- [ ] **Step 2: Run it for real** — `ANON_PROXY_LIVE_TESTS=1 uv run pytest tests/test_backend_parity.py -v` (expect several minutes; fp32 `onnx` should be exactly-equal, quantized variants must at minimum not miss). Record the output — it goes in the PR description.

- [ ] **Step 3: Decide per-variant.** Any variant that misses entities is REMOVED from `BACKENDS`/`ONNX_FILES` in the same commit (don't ship a fast leak). Expect at least fp32 `onnx` to pass; if q4f16 passes, it's the headline backend.

- [ ] **Step 4: Commit**

```bash
git add tests/test_backend_parity.py anon_proxy/privacy_filter.py
git commit -m "test: golden parity gate for onnx backends vs torch reference"
```

---

### Task 4: Server wiring — `--backend onnx-q4f16`

**Files:**
- Modify: `anon_proxy/server.py` (`--backend` choices, the `pf` construction block near `args.backend != "auto"`)
- Modify: `README.md` (backend section)
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `PrivacyFilter(backend=...)` (Task 2), surviving backend names (Task 3).
- Produces: `--backend {auto,cpu,mps,onnx,onnx-int8,onnx-q4f16}` (minus any variant Task 3 killed).

- [ ] **Step 1: Failing test**

```python
def test_onnx_backend_builds_filter_with_backend(monkeypatch):
    """--backend onnx-q4f16 must reach PrivacyFilter(backend=...), not device=."""
    captured = {}

    class FakePF:
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setattr("anon_proxy.server.PrivacyFilter", FakePF)
    # call the config/startup path the existing flag tests use, with
    # ["--backend", "onnx-q4f16"] — mirror the neighboring --chunk-size test.
    assert captured["backend"] == "onnx-q4f16"
    assert captured.get("device") is None
```

- [ ] **Step 2: Verify fail**, then implement in `server.py`:

```python
    if (
        cfg.merge_gap
        or args.chunk_size != DEFAULT_CHUNK_SIZE
        or args.batch_size != 8
        or args.backend != "auto"
    ):
        onnx = args.backend.startswith("onnx")
        pf = PrivacyFilter(
            merge_gap_allowed=cfg.merge_gap or None,
            chunk_size=args.chunk_size,
            batch_size=args.batch_size,
            backend=args.backend if onnx else "torch",
            device=None if (onnx or args.backend == "auto") else args.backend,
        )
```

and extend the choices list. README gains one paragraph: what each backend is, that onnx needs `uv sync --extra onnx`, disk cost of the extra download, and (until Task 5 says otherwise) that it is experimental.

- [ ] **Step 3: Run full suite + lint/format** → green.

- [ ] **Step 4: Commit**

```bash
git add anon_proxy/server.py tests/test_server.py README.md
git commit -m "feat: --backend onnx* server flag wired to PrivacyFilter backends"
```

---

### Task 5: Benchmark gate — does it actually pay?

**Files:**
- Create: `scripts/bench_masking.py` (promoted from the session scratchpad so it survives; exact content below plus the two new arms)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Create `scripts/bench_masking.py`** — the synthetic 12-turn agent replay used for the 2026-07-06 numbers, with onnx arms added:

```python
"""Synthetic perf benchmark for anon_proxy masking.

Simulates agent traffic: N turns, each request carries the FULL history
(the dominant real shape). Measures adapter.mask_request per request with
the real privacy-filter model.

Run:  ANON_PROXY_LIVE_TESTS=1 uv run python scripts/bench_masking.py
"""

import statistics
import time

from anon_proxy.adapters import anthropic as ad
from anon_proxy.default_patterns import DEFAULT_PATTERNS
from anon_proxy.masker import Masker
from anon_proxy.privacy_filter import PrivacyFilter
from anon_proxy.regex_detector import RegexDetector

N_TURNS = 12

PROSE = (
    "We reviewed the deployment pipeline and the rollout looks stable. "
    "Latency percentiles held under the agreed budget through the canary "
    "window, and the error rate stayed flat across all regions. "
)
CODE = (
    "def rollout(stage, replicas):\n"
    "    for r in range(replicas):\n"
    "        client.patch(f'/deploy/{stage}/{r}', json={'weight': r / replicas})\n"
    "    return client.get(f'/deploy/{stage}/status').json()\n"
)


def user_text(i: int) -> str:
    pii = (
        f" Contact Alice Smith at alice.smith@example.com or 555-867-5309 "
        f"about incident {i}."
        if i % 3 == 0
        else ""
    )
    return f"Turn {i}: " + PROSE * 6 + CODE * 4 + pii


def assistant_text(i: int) -> str:
    return f"Reply {i}: " + PROSE * 3


def request_body(n: int) -> dict:
    msgs = []
    for i in range(n + 1):
        msgs.append({"role": "user", "content": user_text(i)})
        if i < n:
            msgs.append(
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": assistant_text(i)}],
                }
            )
    return {"model": "claude-x", "messages": msgs}


def run_arm(name: str, pf: PrivacyFilter) -> None:
    m = Masker(
        filter=pf,
        extra_detectors=[RegexDetector(DEFAULT_PATTERNS)],
        canary="warn",
        min_known_entity_len=6,
    )
    times = []
    for i in range(N_TURNS):
        body = request_body(i)
        t0 = time.perf_counter()
        masked = ad.mask_request(body, m)
        times.append((time.perf_counter() - t0) * 1000)
        assert "alice.smith@example.com" not in str(masked)
    print(
        f"{name}: cold={times[0]:8.1f}ms  "
        f"warm_median={statistics.median(times[1:]):7.1f}ms  "
        f"warm_p95={sorted(times[1:])[-1]:7.1f}ms  "
        f"total={sum(times):8.1f}ms  store={len(m.store)} entries"
    )


if __name__ == "__main__":
    print(f"{N_TURNS} turns, full-history per request, real model\n")
    run_arm("C  torch-cpu   ", PrivacyFilter())
    run_arm("D  onnx-q4f16  ", PrivacyFilter(backend="onnx-q4f16"))
    run_arm("E  onnx-int8   ", PrivacyFilter(backend="onnx-int8"))
```

(2026-07-06 baseline on this machine, for comparison: arm C torch-cpu was cold 5.3s / warm-median 6.6s / p95 8.2s.)

- [ ] **Step 2: Run it** — `uv run python scripts/bench_masking.py`. Record output verbatim.

- [ ] **Step 3: Apply the gate.**
  - **PASS** = best parity-passing onnx arm has warm-median ≤ 70% of arm C (i.e. ≥30% faster). → README: recommend `--backend onnx-q4f16` on CPU-only machines; drop "experimental".
  - **FAIL** → keep torch default and the "experimental" label; the follow-up experiment is the CoreML execution provider (one-line change: `ORTModelForTokenClassification.from_pretrained(..., provider="CoreMLExecutionProvider")` behind a `--backend onnx-coreml` name), and only if THAT fails does an MLX port re-enter the conversation.
  - Either way: paste the numbers into the plan doc `2026-07-06-landing-plan-kevin-migration.md` §Perf validation and into the PR description.

- [ ] **Step 4: Commit**

```bash
git add scripts/bench_masking.py README.md docs/superpowers/plans/2026-07-06-landing-plan-kevin-migration.md
git commit -m "perf: benchmark harness for masking backends + recorded results"
```

---

## PR decomposition

| PR | Tasks | Deliverable a reviewer can observe |
|----|-------|-----------------------------------|
| 1 | Task 1 | `--backend mlx` no longer crashes the server; clean argparse error |
| 2 | Tasks 2+3+4+5 | `--backend onnx-q4f16` works end-to-end, parity-gated, with benchmark numbers in the description |

Task 2 alone would be a PR only validatable by running Task 4's server flag — per the decompose-by-deliverable rule it folds into one PR with its consumers. PR 2's description should lead with the bench table and the parity suite output.

## Upstream issue draft (public — crash bug, not a leak)

> **Title:** `--backend mlx` crashes at startup — no MLX implementation behind the flag
>
> `--backend mlx` (and `--mlx-weights-cache`) are advertised in `--help`, but the value is passed directly to `transformers.pipeline(device=...)`, so startup dies with `RuntimeError: Device string 'mlx' is not recognized`. Repro: `uv run anon-proxy --backend mlx`. Suggest removing the choice until a real fast backend exists. Note: the model repo already ships quantized ONNX exports (`onnx/model_q4f16.onnx`), which may be a cheaper fast path than MLX.
