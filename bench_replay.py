"""Compatibility wrapper for the unified benchmark CLI."""

import sys

from anon_proxy.bench import main


if __name__ == "__main__":
    raise SystemExit(main(["replay", *sys.argv[1:]]))
