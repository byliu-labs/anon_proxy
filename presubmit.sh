#!/usr/bin/env bash
set -euo pipefail

export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"
export UV_TOOL_DIR="${UV_TOOL_DIR:-/tmp/uv-tools}"

uvx ruff@0.15.20 check
uvx ruff@0.15.20 format --check
uv run pytest -v --cov=anon_proxy --cov-report=term-missing --cov-report=xml --cov-fail-under=70
