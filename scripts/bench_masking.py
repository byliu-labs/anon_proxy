"""Compatibility wrapper for the unified synthetic benchmark CLI."""

import sys

from anon_proxy.bench import main


if __name__ == "__main__":
    raise SystemExit(main(["synthetic", *sys.argv[1:]]))
