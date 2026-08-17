# Contributing

anon-proxy is a local-first privacy tool. The contribution bar is simple:
changes must be small, tested, and safe to run without leaking raw PII.

## Setup

Install [uv](https://docs.astral.sh/uv/) and sync the full development
environment:

```bash
uv sync --all-extras --dev
```

For normal torch-free development, use the smaller ONNX path:

```bash
uv sync --extra onnx --dev
```

Optional extras can also be installed one at a time when needed: `torch` for
the reference backend, `menubar` for the macOS indicator, `gen` for committed
dino assets, and `bundle` for PyInstaller packaging.

## Local Checks

Run the focused tests for your change first, then the full local gate:

```bash
uv run pytest -v
uvx ruff@0.15.20 format
uvx ruff@0.15.20 check
./presubmit.sh
```

Benchmarks are not part of every PR, but run them when changing masking,
chunking, batching, backends, or store behavior:

```bash
uv run anon-proxy-bench
ANON_PROXY_LIVE_TESTS=1 uv run --extra onnx python scripts/bench_masking.py
uv run python bench_replay.py
```

Install the optional pre-commit hooks if you want the same formatting checks
before each commit:

```bash
uv tool install pre-commit
pre-commit install
pre-commit run --all-files
```

## Testing Expectations

No commits without tests. Match the test to the behavior:

| Change | Required coverage |
| --- | --- |
| Endpoint or proxy behavior | Integration test with `TestClient` or the proxy harness |
| Adapter masking/unmasking | Adapter test, including streaming when relevant |
| Detector, mapping, or config logic | Unit test with edge cases |
| User-facing CLI, menubar, packaging | CLI or packaging test plus a documented smoke check |
| Backend parity or performance | Existing parity/eval/bench command, usually off the per-PR path |

Masking failures must fail closed. Never add a fallback that forwards raw request
bodies after a detector, adapter, or store error.

## Pull Requests

- Branch from `main`.
- Keep one logical change per PR.
- Prefer Conventional Commit prefixes such as `feat:`, `fix:`, `docs:`,
  `test:`, and `ci:`.
- Link the issue or plan that explains the change.
- Update `CHANGELOG.md` for user-visible changes once the changelog exists.
- Include the exact commands you ran in the PR body.

Security vulnerabilities should not be filed as public issues. Follow
[`SECURITY.md`](SECURITY.md) and email the maintainer first.

Expensive checks such as ONNX parity and release packaging are intentionally
nightly, manual, or tag-triggered. A PR that touches backend equivalence should
state whether `onnx-parity` was run or why it is deferred.
