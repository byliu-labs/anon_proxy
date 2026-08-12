# anon_proxy — masking core

<!-- L2 leaf. Delta only: no restatement of the root CLAUDE.md (architecture, config
     flags, masking invariants live there). No volatile values. Registered in
     docs/context-map.yaml. -->

`anon_proxy/` owns detection, the placeholder mapping, and the HTTP proxy that applies
them. Provider protocol details are NOT here — they live in `adapters/` (see its leaf).

## Layering contract

The three layers must stay separable; a violation is a design bug even when tests pass:

| Layer | Files | Must not know about |
|-------|-------|---------------------|
| Detection | `privacy_filter.py`, `regex_detector.py` | placeholders, HTTP |
| Mapping / masking | `mapping.py`, `masker.py`, `config.py` | HTTP, SSE, provider shapes |
| Transport | `server.py`, `upstream.py`, `capture.py` | detector internals, model chunking |

## Package-specific gotchas

- **Regex runs before the ML model, by design.** `Masker` substitutes regex hits inline,
  then runs the transformer over the partially-masked text. This preserves sentence
  context for the model while letting high-precision patterns win. Reordering these two
  silently degrades recall — it does not fail a unit test of either detector alone.
- **Chunking is a model constraint, not a masking one.** `privacy_filter.py` splits long
  text for inference and merges adjacent entities across the seam (`merge_gap`). Entity
  spans returned to `Masker` are always in original-text coordinates.
- **`PIIStore` is persistent and append-mostly.** It is the reason placeholders stay
  stable across turns. Writes go through `_maybe_save_store`; never rewrite the file
  in place from request-handling code.
- **`server.py` is the only module that may touch bytes on the wire.** Streaming
  substitution happens as chunks arrive, so a placeholder split across two SSE frames is
  a real case — `adapters/_streaming.py` handles the buffering.

## Related docs (up the tree)

- Root `CLAUDE.md` — architecture, config flags, masking invariants, toolchain
- `anon_proxy/adapters/CLAUDE.md` — per-provider request/response shapes
- `docs/local/` — benchmarks, ONNX backend evaluation, fork-divergence decision
