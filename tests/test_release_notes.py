from __future__ import annotations

from pathlib import Path

import pytest

from anon_proxy.release_notes import extract_changelog_entry, write_release_notes


def test_extract_changelog_entry_for_tag():
    changelog = """# Changelog

## [1.2.0] - 2026-08-17
- Harden release notes.

## [1.1.0] - 2026-08-10
- Older entry.
"""

    assert extract_changelog_entry(changelog, "v1.2.0") == (
        "## [1.2.0] - 2026-08-17\n- Harden release notes."
    )


def test_extract_changelog_entry_requires_matching_tag():
    with pytest.raises(ValueError, match="CHANGELOG.md has no section for v9.9.9"):
        extract_changelog_entry("## [1.0.0]\n- Existing", "v9.9.9")


def test_write_release_notes(tmp_path: Path):
    changelog = tmp_path / "CHANGELOG.md"
    output = tmp_path / "release-notes.md"
    changelog.write_text("## [1.0.0]\n- First\n", encoding="utf-8")

    write_release_notes(changelog, output, "v1.0.0")

    assert output.read_text(encoding="utf-8") == "## [1.0.0]\n- First\n"
