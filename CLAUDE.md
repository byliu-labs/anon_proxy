# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Context tree.** L0 (this file) = orientation + laws + index. L2 = `anon_proxy/CLAUDE.md`
and `anon_proxy/adapters/CLAUDE.md` package leaves, auto-loaded when you work in those
directories. A child never restates this file — it links up. Ownership map:
[`docs/context-map.yaml`](docs/context-map.yaml); the advisory `check-context-map-fresh.sh`
hook nudges when mapped code changes without its owning doc. `AGENTS.md` is a symlink to
this file, so Codex and Claude read one source.

## Project overview

An LLM API proxy that transparently masks PII before requests leave the device and unmasks it in responses. The OpenAI Privacy Filter model runs locally — raw PII never reaches the upstream API.

## Commands

```bash
# Install dependencies
uv sync

# Test the PII detector interactively
uv run python test_filter.py "Alice Smith called from 555-867-5309"

# Interactive chat through the mask/unmask layer (needs ANTHROPIC_API_KEY)
uv run python test_mask.py

# Run the proxy server
uv run python -m anon_proxy.server [options]
# or
uv run python main.py [options]
```

## Architecture

The codebase is organized into five core responsibilities that remain cleanly separable:

1. **`privacy_filter.py`** — Local PII detection using the OpenAI Privacy Filter model (HuggingFace). Handles chunking for long texts, adjacency merging for multi-word entities, and configurable per-label merge gap rules.

2. **`regex_detector.py`** — Supplementary regex-based PII detector for patterns the ML model misses (SSNs, IPs, etc.). Patterns come from the unified `config.json` (`patterns` section).

3. **`mapping.py` + `masker.py`** — Persistent bidirectional mapping (`PIIStore`) and masking orchestration. Same entity gets same placeholder across requests. The `Masker` runs regex detectors first and substitutes their matches inline, then runs the ML model on the partially-masked text — this preserves transformer context while letting high-precision regex hits take precedence. Also drops ML-detected entities whose label is in `ignore_labels`.

4. **`config.py`** — Unified config loader. `Config` dataclass holds `patterns`, `merge_gap`, `ignore_labels`; `load_config(path)` parses and validates `config.json`.

5. **`server.py` + `adapters/`** — HTTP proxy (Starlette/Uvicorn) that applies mask on outbound and unmask on inbound. Currently Anthropic-specific; OpenAI adapter is planned (see README roadmap).

Key design invariants:
- Masking layer should not know about HTTP
- Proxy layer should not know about detector internals
- Adapters isolate provider-specific protocol details (SSE parsing, message shape)

## Configuration

Server flags (all have `ANON_PROXY_*` env var equivalents):
- `--host` / `--port` — bind address
- `--upstream` — target API URL (default: Anthropic)
- `--debug` — log masked/unmasked diffs to stderr
- `--config <file>` — unified `config.json` with optional keys `patterns` (extra regex detectors), `merge_gap` (per-label adjacency merge chars), `ignore_labels` (ML-detected labels to skip masking)
- `--chunk-size <N>` — max chars per model inference pass (default: 1500)

## Toolchain

- Python `>=3.10` (pinned in `.python-version`)
- `uv` as package manager — use `uv add <pkg>` for dependencies
- `uvicorn` for server (ASGI)
- `transformers` + `torch` for local PII model
- `pytest` for tests, `ruff` for lint, GitHub Actions CI (`.github/workflows/ci.yml`)
- `bash presubmit.sh` before pushing — it runs what CI runs

## Masking invariants (Never Violate)

The whole product is "raw PII never leaves the device." Each of these is covered by a
test today; none may be relaxed for convenience:

- **Placeholders are stable per store, not per request.** The same entity gets the same
  placeholder across turns — that is what keeps the model coherent. Never mint a fresh
  placeholder for an entity already in `PIIStore`
  (`test_same_canonical_returns_same_placeholder_no_counter_bump`).
- **Unmask is the exact inverse of mask**, in streaming and non-streaming paths alike,
  including a placeholder split across two SSE deltas
  (`test_placeholder_split_across_two_deltas`).
- **Masking failures are not swallowed.** `adapter.mask_request` is deliberately *not*
  wrapped in a `try/except` at its `server.py` call site: a detector or adapter error
  fails the request rather than forwarding it raw. Do not add a catch there.

### The known passthrough gaps (deliberate, but they ARE gaps)

`_handle_proxy` forwards the body **unmasked** when it is empty, `multipart/form-data`,
or not valid JSON, and `_should_mask_request` exempts `count_tokens` (masking changes
text length, so the count would be wrong anyway). These are decisions, not oversights —
but they mean "nothing unmasked ever leaves" is not literally true. Before widening a
passthrough, add the test first; before narrowing one, check the `count_tokens` length
argument still holds.
