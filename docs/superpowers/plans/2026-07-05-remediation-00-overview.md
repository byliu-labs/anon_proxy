# anon-proxy Remediation — Overview & PR Sequencing

> **For agentic workers:** This is the index. Each numbered plan file in this
> directory is ONE PR. Execute plans with superpowers:subagent-driven-development
> or superpowers:executing-plans, one plan (= one branch = one PR) at a time.

**Goal:** Make anon-proxy actually deliver its promise ("raw PII never reaches the
upstream API") at ≤1.5× e2e latency, for both single-laptop and shared-k8s users.

**Source:** 2026-07-05 design review (see `2026-07-05-review-issue-drafts.md` in
this directory for the issue text; leaks 1–3 are security-sensitive — coordinate
with Kevin privately before public PR descriptions name them as leaks).

## Global constraints (apply to every PR)

- Python ≥ 3.10, `uv` for everything (`uv run pytest`, `uv add`), ruff format.
- TDD: failing test first, then code. Run `uv run pytest tests/ -q` (full suite,
  329 passing baseline) before every commit; `--collect-only` check when a public
  signature changes.
- One branch per plan, branched from up-to-date `main`. No commits to `main`.
- Every PR description states which review finding / GitHub issue it addresses.
- Fail-closed principle: no change may add a path where unscanned text reaches
  the upstream socket. Perf is recovered by caching/batching, never by skipping.
- Security-sensitive wording: PRs 01/02 fix leaks. Keep PR titles neutral
  ("mask system-reminder content", "mask count_tokens requests") — details go to
  Kevin privately first, per SECURITY.md.

## PR sequence and dependencies

| # | Plan file | PR (one line) | Fixes | Depends on |
|---|-----------|---------------|-------|-----------|
| 01 | `...01-remove-system-reminder-skip.md` | Stop skipping `<system-reminder>` blocks — mask them | Leak 1 | — |
| 02 | `...02-mask-count-tokens.md` | Mask `count_tokens` request bodies | Leak 2 | — |
| 03 | `...03-unknown-placeholder-detection.md` | Warn loudly when a response contains a placeholder not in the store | #13 (half) | — |
| 04 | `...04-detection-off-event-loop.md` | Run detection in a worker thread; make store/caches thread-safe | #6 | — |
| 05 | `...05-batched-inference-and-chunk-size.md` | Batch chunk inference; raise default chunk size | #6 | 04 |
| 06 | `...06-remove-429-retry.md` | Stop retrying 429s inside the proxy | #12 | — |
| 07 | `...07-cache-usage-metrics.md` | Surface `cache_read_input_tokens` in `--metrics` | #12 (diagnosis) | — |
| 08 | `...08-fail-closed-masking.md` | Invert adapters to fail-closed: mask every string leaf unless whitelisted | Leak 3 | 01, 02 |
| 09 | `...09-multi-user-store.md` | `--multi-user`: per-client store namespacing keyed by auth hash | Oracle flaw | — |
| 10 | `...10-default-secrets-pack.md` | Ship default regex pack (emails, phones, SSNs, keys, JWTs) | #1 | — |
| 11 | `...11-post-mask-canary.md` | Post-mask regex canary (warn/fix modes) | #1 | 10 |
| 12 | `...12-known-entity-matching.md` | Exact-match already-known store values anywhere (incl. code) | #1, #13 | 11 |
| 13 | `...13-min-score-threshold.md` | `min_score` config knob for ML detections (**gate on replay evidence**) | #13 | — |
| 14 | `...14-store-cli.md` | `anon-proxy-store list/show/purge/prune` | #13 cleanup | — |

**Waves:** A = 01–03 (leak fixes, ship first, tiny). B = 04–05 (perf to 1.5×,
validate with `bench_replay.py` + a live Claude Code session). C = 06–07 (#12).
D = 08–09 (architecture). E = 10–13 (detection quality). F = 14 (tooling).

Within a wave PRs are independent; land waves in order. 08 should land after
01/02 so the fail-closed walker's tests assert the already-fixed behavior rather
than re-fixing it.

## Validation gates (per wave)

- **Wave A:** `--debug` run with Claude Code; confirm system-reminder / userEmail
  content shows a masked diff; confirm count_tokens requests log `[masked]`.
- **Wave B:** `uv run python bench_replay.py --capture <real capture>` before/after;
  live Claude Code session timing vs no-proxy — target ≤1.5× e2e.
- **Wave C:** `--metrics` line shows cache_read tokens; 429 passes through
  with Retry-After intact (curl a stubbed 429 upstream).
- **Wave D:** leak-attempt test: request with PII in an *unknown* field → masked;
  two clients in multi-user mode cannot unmask each other's tokens.
- **Wave E:** `test_filter.py` on clue-less inputs ("442 222 47571" bare) masks;
  canary fires on a seeded ML miss; replay a captured session and count
  store-pollution delta.

## Issue mapping

- GitHub #1 → PRs 10, 11, 12, 13
- GitHub #6 → PRs 01 (removes the bad fix), 04, 05
- GitHub #12 → PRs 06, 07, 09
- GitHub #13 → PRs 03, 12, 14 (+ z.ai `--capture` investigation, not a PR yet)
- Review leaks 1–3 → PRs 01, 02, 08; unmask-oracle → PR 09
