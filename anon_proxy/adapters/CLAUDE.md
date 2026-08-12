# anon_proxy/adapters — provider protocol adapters

<!-- L2 leaf. Delta only. Registered in docs/context-map.yaml. -->

`anon_proxy/adapters/` isolates everything provider-specific: where the text lives in a
request body, how a response is shaped, and how that provider frames its SSE stream.
Detection and placeholder policy are NOT here — that is the masking core's job.

## The adapter contract

Every adapter implements exactly three entrypoints, and nothing outside the adapter may
branch on provider name:

| Function | Responsibility |
|----------|----------------|
| `mask_request(body, masker)` | walk the provider's body shape, mask every text-bearing field |
| `unmask_response(body, masker)` | exact inverse over the response shape |
| `transform_stream(upstream_bytes, masker)` | async iterator, unmasking across frame boundaries |

Adding a provider = a new module registered in `__init__.py` + a full test triple
(`test_adapter_<name>.py` plus a streaming case). A provider wired into `server.py`
without `transform_stream` coverage will leak placeholders to the client mid-stream.

## Package-specific gotchas

- **Text lives in more places than the obvious one.** System prompts, tool definitions,
  tool results, and assistant turns all carry user PII. Masking only `messages[].content`
  is the recurring bug — walk the whole body.
- **Stream buffering is shared.** `_streaming.py` holds the partial-token buffer so a
  placeholder split across SSE chunks still unmasks. Do not reimplement per adapter.
- **Byte-count fields are provider-visible.** Placeholders change text length, so any
  field the provider derives from length (usage counts, token estimates) is not
  round-trippable — the `count_tokens` path is deliberately exempt from masking.

## Related docs (up the tree)

- `anon_proxy/CLAUDE.md` — layering contract, detector ordering, `PIIStore`
- Root `CLAUDE.md` — masking invariants (fail closed, stable placeholders, inverse)
