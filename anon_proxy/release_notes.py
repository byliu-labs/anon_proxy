"""Release-note extraction helpers for tagged GitHub releases."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def extract_changelog_entry(changelog: str, tag: str) -> str:
    version = tag.removeprefix("v")
    pattern = rf"^## \[{re.escape(version)}\].*?(?=^## \[|\Z)"
    match = re.search(pattern, changelog, flags=re.M | re.S)
    if not match:
        raise ValueError(f"CHANGELOG.md has no section for {tag}")
    return match.group(0).strip()


def write_release_notes(changelog_path: Path, output_path: Path, tag: str) -> None:
    changelog = changelog_path.read_text(encoding="utf-8")
    output_path.write_text(
        extract_changelog_entry(changelog, tag) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tag")
    parser.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    parser.add_argument("--output", type=Path, default=Path("release-notes.md"))
    args = parser.parse_args(argv)

    write_release_notes(args.changelog, args.output, args.tag)


if __name__ == "__main__":
    main()
