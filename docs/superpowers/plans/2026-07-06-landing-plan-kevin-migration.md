# Landing plan: moving the remediation waves to Kevin's repo

**Status as of 2026-07-06 (second pass).** All seven waves are reviewed,
integrated into one linear stack on the fork, and mirrored as stacked PRs
#10–#16 on `byliu-labs/anon_proxy`. The merged implementation lives on
`land/integration` (= `land/07-store-cli` tip): **405 tests green**.
Fork `main` is synced to upstream (`1bd427c`). Old PRs #2–#9 are closed
as superseded.

## Review verdicts (final, evidence-based)

| Wave | Verdict | Where it lives now | Evidence |
|------|---------|--------------------|----------|
| A — leak fixes | Approve | `land/01-mask-gaps` (PR #10) | 333 green on branch |
| C — 429 + cache metrics | Approve | `land/02-429-metrics` (PR #11) | 322 green |
| B — perf off-loop + batching | Approve | `land/03-perf-offloop` (PR #14) | live-model probe: PII at offset 5131 in one 6000-char chunk, score 1.0; bench below |
| D₁ — fail-closed policy | Approve (holes to sign off) | `land/04-fail-closed-policy` (PR #12) | 339 green |
| D₂ — multi-user + 0600 hardening | Approve | `land/05-multi-user` (PR #13) | 351 green; perms tests |
| E-rebuild — detection quality | Approve (was: rebuild required — done) | `land/06-detection-quality` (PR #15) | 393 green; half-wiring fixed in review (see below) |
| F-rebuild — store CLI | Approve (was: rebuild required — done) | `land/07-store-cli` (PR #16) | 405 green; both review bugs fixed (bare-prune guard, purge not-found) |

Rebuild review notes:
- **E-rebuild** (`b1ac5af`) is the correct port: known-entity pass-0 before
  the regex pre-pass, canary reusing the existing `_drop_placeholder_overlaps`,
  config-file validation for the three new knobs. One integration bug found
  and fixed during stacking: the **multi-user `make_masker` closure did not
  thread `canary`/`min_known_entity_len`** — per-client maskers would have
  silently lost detection-quality features. Fixed in the `land/06` commit.
- **F-rebuild** (`9464d5d`) fixes both review-found bugs properly and its
  `atomic_write_json` is byte-identical to the 0600 hardening version, so
  stacking reconciled to a single helper in `mapping.py`; the server's
  duplicate `_write_store_json` wrapper is deleted.

## The stack (fork PRs #10–#16, each based on the previous)

| # | Fork PR | Branch | Real size | Suite |
|---|---------|--------|-----------|-------|
| 1 | #10 | `land/01-mask-gaps` | +111/−52 | 333 |
| 2 | #11 | `land/02-429-metrics` | +171/−161 | 322 |
| 3 | #14 | `land/03-perf-offloop` | +229/−72 | green |
| 4 | #12 | `land/04-fail-closed-policy` | +239/−160 | 339 |
| 5 | #13 | `land/05-multi-user` | +302/−24 +perms | 351 |
| 6 | #15 | `land/06-detection-quality` | ~+480 | 393 |
| 7 | #16 | `land/07-store-cli` | ~+380 | 405 |

`land/integration` = tip of #16 (`d195a67` after the 2026-07-06 restack).
All integration conflicts are already resolved in the stack commits —
landing in order needs no manual conflict work.

**Restack note (2026-07-06 late):** running the repo's exact CI jobs locally
caught two issues the test suite couldn't: a formatting violation and a
zombie test (`test_max_retries_parameter` — mocks set up for the deleted
429-retry feature, zero assertions, passed vacuously; a leftover of the B×C
conflict resolution). Both fixed inside the land/03 and land/05 commits and
the stack force-pushed; PR heads #10–#16 verified to match
(`ac1517e/0d3ab94/9a9ef10/f47f475/d577980/8e9d363/d195a67`), all
`mergeable=true`. **ruff check + ruff format --check + pytest now pass at
every stack level.**

**CI caveat:** the fork's CI workflow only triggers on PRs whose base is
`main`, so only PR #10 has real CI runs (8/8 success on `ac1517e`). PRs
#11–#16 show no checks on the fork — the identical jobs (ruff check, ruff
format --check, pytest) were run locally at every level instead. On Kevin's
repo every PR will be opened against `main` sequentially, so each gets CI.

## Step-by-step: what to do now (sequenced)

### Phase 0 — before anything touches Kevin's repo

1. **Send Kevin the private security note** (draft in
   `2026-07-05-review-issue-drafts.md`, same directory). It covers the three
   leaks (system-reminder skip, count_tokens passthrough, Responses-API
   `input`), the unmask-oracle, and now also the world-readable store files.
   Do NOT file these as public issues (SECURITY.md).
2. Optionally file the **non-security public issues** from the same draft
   file, plus one new one found this round: **`--backend mlx` crashes at
   startup** — README advertises MLX for Apple Silicon but no MLX code path
   exists; `PrivacyFilter(device="mlx")` →
   `RuntimeError: Expected one of cpu, cuda, … device type at start of
   device string: mlx`. This matters because MPS is measurably *worse* than
   CPU (bench below), so MLX is the only credible Apple-Silicon fast path.
3. Give Kevin a heads-up on the plan: 7 PRs, sequenced, ~100–500 lines each,
   review order fixed by the stack.

### Phase 1 — self-review on your fork (already set up)

The fork PRs #10–#16 ARE the dry run. Each shows exactly the diff Kevin
will see. Read them top to bottom in order; anything you'd change, push a
fixup to the corresponding `land/*` branch (and rebase the branches above
it: `land/0N+1` onto the new `land/0N`, … — or ask Claude to redo the
restack, it's mechanical).

To try the merged build locally:

```bash
git fetch fork land/integration
git checkout fork/land/integration
uv run python -m anon_proxy.server --debug --metrics
# then point Claude Code at it:
ANTHROPIC_BASE_URL=http://127.0.0.1:8080/anthropic claude
```

Watch stderr for: `[metrics …] tokens: in=… cache_read=…` (PR #11),
canary warnings (PR #15), unknown-placeholder warnings (PR #10).

### Phase 2 — migrate to Kevin's repo, one PR at a time

For each i in 1..7, after the previous PR merged:

```bash
# first PR only: branch straight off Kevin's main
git push origin land/01-mask-gaps:refs/heads/fix/mask-gaps   # or open from fork

# open PR on KevinXuxuxu/anon_proxy with base=main, head=<branch>
# copy title+body from the corresponding fork PR (#10–#16)
```

Practical notes:
- GitHub fork-PR flow works directly: open the PR on Kevin's repo with
  `head=byliu-labs:land/0N-…`, `base=main`. No pushing to his repo needed.
- **PR N>1 must wait for PR N−1 to merge**, then change nothing if Kevin
  merges cleanly (GitHub recomputes the diff against updated main). If he
  squash-merges, rebase the next branch onto his new main first:
  `git rebase --onto origin/main land/0(N−1)-… land/0N-…` — conflicts will
  be empty/trivial because the content is identical.
- Keep titles neutral for #10/#12/#13 (they fix leaks; the private note has
  already told Kevin what they are).
- After all 7 merge upstream: delete the `land/*` branches and close the
  fork PRs; fork main fast-forwards again.

### Phase 3 — after landing

- Live A/B check of #12 (GLM/z.ai 429s) using `--metrics` cache_read data.
- Plan 13 (min_score) stays blocked until a polluted `--capture` exists.
- File the z.ai SSE framing investigation if #13 symptoms persist.

## What to do with your own fork (summary)

- `main`: synced to upstream; keep it that way (`git push fork origin/main:main` after each upstream pull).
- `land/01…07`, `land/integration`: the deliverable. Don't commit to them except review fixups.
- PRs #10–#16: the review mirror. #2–#9 are closed; their branches
  (`fix/mask-count-tokens`, `codex/*`, `feat/store-cli*`, `codex/base-origin-main`)
  are now redundant — delete when convenient.
- Old experiment branches (`telemetry*`, `split/*`, `publishing-and-promotion`, …)
  are untouched by this plan.

## Perf validation (synthetic bench, this machine, 2026-07-06)

12-turn agent-style replay, each request carries full history (~31KB by the
end), real `openai/privacy-filter`, PII in every third turn. Script:
scratchpad `bench_synthetic.py`. Numbers are per-request `mask_request` time.

| Arm | cold | warm median | warm p95 | total |
|-----|------|-------------|----------|-------|
| A: chunk 1500, batch 1, extras off (≈ pre-stack) | 9.0s | 8.7s | 10.1s | 107.2s |
| B: chunk 6000, batch 8, extras off | 6.2s | 6.4s | 7.1s | 77.9s |
| C: = B + default patterns + canary + known-entities (shipping config) | 5.3s | 6.6s | 8.2s | 81.1s |
| C on MPS (`--backend mps`) | 6.1s | 10.0s | 16.4s | 129.3s |

Read-outs:
- **Caches work as designed**: warm ≈ cold even though history grows 12× —
  only the NEW turn is ever inferenced. This is the load-bearing perf design
  and it holds.
- **Wave B is real**: ~26% faster per new turn on CPU (8.7 → 6.4s median).
- **Wave E costs ~2–4%** (6.4 → 6.6s). Cheap insurance.
- **MPS is a trap on this machine**: 1.5× slower than CPU with huge p95 —
  MPS recompiles kernels per sequence length and every turn has a new
  length. Keep `auto` = CPU on macOS; don't recommend `--backend mps`.
- **The 1.5× e2e target**: masking adds ~6.5s per turn of new content
  (~3KB). Against a typical 15–60s Claude Code turn that is 1.1–1.4× —
  inside target. Against short interactive turns (<10s) it exceeds 1.5×.
  The lever is inference speed, and the honest options are: a working MLX
  backend (currently a crashing flag), a quantized/smaller model, or CUDA.
  This is the #1 remaining perf workstream.

**Follow-up plan written (2026-07-06):** `2026-07-06-onnx-inference-backend.md`
(same directory). Key discovery that redirects it: the model repo already
ships quantized ONNX exports (`onnx/model_q4f16.onnx` ≈ 0.77 GB vs 2.6 GB
safetensors), and the architecture is custom (`openai_privacy_filter`,
sliding-window attention, Viterbi-calibrated decode) — so the plan is an
ONNX Runtime backend behind the existing HF pipeline surface (parity-gated,
benchmark-gated), NOT a from-scratch MLX port. The plan also carries the
standalone `--backend mlx` crash fix and preserves the bench script as
`scripts/bench_masking.py`. Not yet executed.

## Telemetry: current state (answer to "do we have good telemetry yet?")

**Have (after the stack):**
- Per-request phase timings via `telemetry_scope` → `--capture` `timing_ms`
  (mask/unmask ms, chars, cache hits per call).
- `--metrics` per-turn line: e2e / upstream / proxy-share, plus token usage
  incl. `cache_read` / `cache_creation` (the #12 instrument).
- `unknown_tokens` count per unmask (model-invented placeholders).
- Canary warnings on stderr when PII survives masking (detection-quality
  signal, free in production).
- `bench_replay.py` for apples-to-apples replay of a capture.

**Missing (in priority order):**
1. **Detection-score telemetry** — per-entity label + score distribution.
   Without it plan 13 (min_score) stays evidence-blocked. Cheapest version:
   include label+score histograms in `--capture` records.
2. Aggregates — nothing rolls up p50/p95 mask latency or cache-hit rate over
   a session; you eyeball stderr. A `--metrics-summary` on shutdown would do.
3. Canary hit *rate* as a counter (warnings exist, counts don't).
4. Structured (JSON-lines) log option — roadmap "Observability" item; all
   current output is human-formatted stderr.

Verdict: good enough to verify the perf claims and to diagnose #12;
not yet good enough for detection-quality tuning (that needs item 1).

**Follow-up plan written (2026-07-06):** items 1–4 are fully planned as
PR-sized TDD tasks in `2026-07-06-detection-telemetry.md` (same directory) —
per-entity score telemetry + `anon-proxy-capture-report` histogram tool
(unblocks plan 13), `MaskerStats` session aggregates with shutdown dump,
`--log-json` structured logs. Not yet executed.

## Nits to fold in while landing (unchanged, still open)

- **A:** init `_last_unknown_count = 0` in `Masker.__init__`; dedupe repeated
  unknown-token warnings within one SSE stream.
- **B:** extract `DEFAULT_BATCH_SIZE = 8` (duplicated in server condition).
- **D:** decide on masking `metadata`; consider parse-then-mask for OpenAI
  `function.arguments`; `registry.get` does disk I/O on the event loop for a
  client's first request; `policy._walk`/`_walk_value` duplicated dict branch.

## Validation log (what was actually run, cumulative)

- Branch suites: A 333 / C 322 / B 333 / D 346 / E-rebuild 371 / F-rebuild 334.
- Stack suites: land/04 339, land/05 351, land/06 393, land/07 = integration 405.
- Live model probes: 6000-char chunk detection (offset 5131, score 1.0);
  `--backend mlx` crash reproduced.
- Synthetic perf bench: 4 arms (table above).
- Live CLI smoke (F): list/prune/purge, counters preserved, .bak, dry-run,
  bare-prune footgun confirmed → fixed in rebuild → guard verified in tests.
- Fork: main synced; `land/01..07` + `land/integration` pushed; PRs #10–#16
  opened; #2–#9 closed with pointers.
- CI parity: ruff check + ruff format --check + pytest run locally at every
  stack level (the repo CI's exact jobs), all green post-restack; PR #10 CI
  8/8 success.
- **Live E2E (16/16 checks)** — scratchpad `e2e_live.py`: real
  `python -m anon_proxy.server` subprocess (real `main()` parsing
  `--multi-user --store --canary --min-known-entity-len --batch-size
  --debug --metrics`), real sockets, real model, local mock upstream.
  Verified over the wire: raw PII never reached the upstream (messages AND
  count_tokens); client responses fully reconstructed (JSON and streaming
  SSE deltas, no placeholder leaked); `[metrics] cache_read=` emitted on
  both paths; multi-user oracle closed (client C cannot unmask A's tokens),
  401 without credential, per-client store files 0600 in a 0700 dir;
  single-user `--store` persisted 0600. Bonus finding: the injected
  placeholder-explainer prompt contains example tokens (`<EMAIL_2>`,
  `<PHONE_1>`) — if a model echoes them they pass through un-unmasked with
  a warning; harmless but explains stray unknown-token warnings in logs.
