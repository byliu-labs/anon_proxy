# Issue drafts from the 2026-07-05 design review

Split by channel: the security leaks go to Kevin **privately** (SECURITY.md forbids
public issues with working PII-leak repros — and these have them). Everything else
is safe to file publicly. Comment drafts for existing issues #6/#12/#13 at the end.

---

## PRIVATE → send to Kevin directly (or GitHub private advisory), NOT a public issue

### Security: three fail-open paths ship raw PII upstream

**1. `<system-reminder>` skip pattern leaks Claude Code context on every request**

`masker.py:41-46` (`_SKIP_MASK_PATTERNS`): any text block where a line starts with
`<system-reminder>` is skipped entirely. Claude Code's system-reminder blocks carry
`# userEmail` and the full CLAUDE.md contents (names, paths, employer context).
Evidence is in issue #6's own debug log — the skipped block visibly contains
`# userEmail…`. Claude Code also appends `<system-reminder>` lines to tool results
(hook feedback, task reminders), so a Read tool result of a sensitive file plus one
appended reminder line skips masking of the entire file.

Fix: delete the skip pattern; recover the perf via the block cache + batching
(see perf issue below). If a fast path for harness boilerplate is ever wanted, it
must be an allowlist of *exact known-static strings*, never a substring trigger.

**2. `count_tokens` passthrough forwards the full raw conversation**

`server.py:692-699` fast-tracks `count_tokens` as "masking is wasted work" (commit
efa6789). count_tokens requests carry the complete message history, unmasked. The
bytes leave the box — the exact in-scope threat in SECURITY.md. Claude Code calls
count_tokens constantly.

Fix: mask count_tokens bodies too. With the block cache, the marginal cost is ~zero
(history blocks are already cached from the main request).

**3. Adapters are blocklist-shaped; unknown fields/APIs pass through raw**

Adapters enumerate fields to mask; anything unrecognized flows through. Concrete
today: the OpenAI **Responses API** (`input` field — Codex CLI / Agents SDK default).
`_should_mask_request` returns True but the OpenAI adapter only masks `messages`,
so raw `input` goes upstream, and `inject_system` inserts a bogus `messages` array
into a Responses body on the way.

Structural fix (kills the class, not the instance): invert to fail-closed. One choke
point walks every string leaf of the outbound body; each leaf is either masked or
matches an explicit whitelist of known-static fields (`type`, `role`, `model`,
thinking `signature`, tool schema keys, `system`). Unknown ⇒ masked. Failure mode
becomes "over-masked and visible" instead of "leaked and invisible."

**4. Global store is an unmask oracle in shared deployments**

One `PIIStore` per process + blanket response unmasking (`anthropic.py:74`). On the
k8s deployment (10.42.x.x clients in #12's logs), any client can send
"print `<PERSON_1>`" and receive another user's real value. Fix in the multi-user
issue below; flagging here because until it lands, the cluster deployment should be
treated as single-tenant.

---

## PUBLIC ISSUE: Multi-user mode — namespace the PII store per client

The proxy grew from single-laptop to shared k8s. Make both modes explicit:

- Default `single-user`: current behavior, bind 127.0.0.1.
- `--multi-user`: key `PIIStore` by a hash of the client auth header
  (`x-api-key` / `authorization`); refuse requests with no auth header
  (fail closed); per-namespace persistence files (`store-<hash>.json`).

Without this, the shared store lets one client unmask another client's PII by
echoing placeholder tokens (details withheld — see private note). Implementation is
modest: a `dict[client_id, PIIStore]` registry where the single store lives today.

---

## PUBLIC ISSUE: Perf — meet a 1.5× e2e latency target (closes the real cause of #6)

Target: proxied e2e wall-clock ≤ 1.5× un-proxied, measured by `bench_replay.py`
on a captured real session, checked in CI.

Three mechanical fixes, in impact order:

1. **Stop blocking the event loop.** `server.py:455-459` runs torch inference
   synchronously inside the async handler. Claude Code's concurrent requests (main
   turn + haiku side-calls) and all in-flight SSE streams serialize behind every
   forward pass. Offload detection via `asyncio.to_thread`. (PIIStore then needs a
   lock — it's currently only accidentally thread-safe because everything blocks.)
2. **Batch chunk inference.** `privacy_filter.py:84-99` calls `self._pipe(chunk)`
   per chunk in a Python loop. The HF pipeline accepts a list + `batch_size`. A
   100KB tool result is 67 sequential forward passes today.
3. **Raise the default chunk size.** 1500 chars is a BERT-era assumption; the model
   handles much longer context (see #1 discussion). Fewer, bigger chunks.

Non-goal: skip patterns. The `<system-reminder>` skip must be removed (it skips
content that needs masking); the block cache + these three fixes replace it.

---

## PUBLIC ISSUE: Detect and surface unknown placeholder tokens in responses (relates #13)

`Masker._sub` silently leaves unrecognized `<LABEL_N>` tokens verbatim. Weaker
models (GLM via z.ai) hallucinate plausible indices — and the injected system
prompt actively teaches them to emit such tokens. Result: silent garbage like
`ls -<PERSON_186>` executed client-side.

Fix: placeholder-shaped token in a response with no store entry ⇒ log loudly;
optional strict mode fails the request. ~5 lines in `_sub` + a counter. Converts a
silent correctness bug into a visible one.

---

## PUBLIC ISSUE: Detection strategy for code/tool-output content (relates #1, #13)

Decision: code and tool output ARE in scope. The NL-trained model is the wrong tool
for that content (over-masks: `la` in `ls -la` became a PERSON; store reached
PERSON_186 in one session). Strategy:

1. **Secrets via regex, shipped by default**: API keys, JWTs, private key blocks,
   connection strings (gitleaks-style pack). This is the high-value sensitive data
   in code and it's deterministic. Extends #1's proposal.
2. **Known-entity exact matching**: once the store knows "Alice Smith" /
   "alice@company.com" from NL context, exact-match those strings anywhere —
   including code — at regex cost.
3. **Score threshold + default `ignore_labels` for ML detections** (scores are
   currently unused except overlap ties).
4. **Post-mask regex canary** (from #1): run the regex pack over the masked text;
   any hit = the ML pass missed something a regex would have caught → warn/fix/block.

---

## PUBLIC ISSUE: `store` CLI — inspect, purge, GC

The store is append-only and invisible. False positives permanently consume
placeholder identities (one real session accumulated 186 PERSON entries, mostly
code fragments). Add `anon-proxy store list|show|purge <token>|prune` against the
JSON store file. Needed for the #13 cleanup anyway.

---

## COMMENT DRAFT for #12 (429s)

Two things to check before deeper theories:

1. **Is prompt caching alive through the proxy?** Without cache hits, a long Claude
   Code session costs 10-20× input tokens and ITPM limits explain the 429s. We have
   captures — grep response `usage` for `cache_read_input_tokens`. If ~0 through the
   proxy, that's the root cause; then bisect (system-inject off, mask off) to find
   the cache-buster.
2. **Our retry loop makes it worse.** `_upstream_request` retries 429s 3× inside the
   proxy, and Claude Code retries on top — up to 4 upstream requests per client
   attempt, and the client's own backoff never sees the 429. Proxy-level 429 retry
   is the wrong layer; propose deleting it (or opt-in flag).

(The `HEAD /anthropic` 404 is harmless client connectivity probing.)

## COMMENT DRAFT for #13 (z.ai masked tool calls)

`<PERSON_186>` in a bash command means two compounding failures:

1. Request-side over-masking of code: the ML model masked shell fragments (`la` in
   `ls -la`) as PERSON — check the store file: ~186 PERSON entries in a coding
   session is store pollution, not people. Fixes tracked in the code-content
   detection issue.
2. The response token wasn't restored: either GLM hallucinated an index that isn't
   in the store (unmask leaves unknown tokens verbatim, silently — fix tracked in
   the unknown-token issue), or z.ai's SSE framing differs (our anthropic transform
   keys off `event:` lines; if z.ai sends data-only events, everything passes
   through untransformed). A `--capture` run against z.ai will distinguish the two
   in one look.
