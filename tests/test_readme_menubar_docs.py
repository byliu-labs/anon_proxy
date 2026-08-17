from pathlib import Path


README = Path(__file__).resolve().parent.parent / "README.md"


def test_readme_documents_menubar_start_proxy_command():
    text = README.read_text()

    assert text.count("```") % 2 == 0, "README has unbalanced code fences"
    assert "## Menu-bar" in text
    assert "uv sync --extra menubar" in text
    assert "uv run anon-proxy-menubar" in text
    assert "uv run anon-proxy-menubar --start-proxy" in text
    assert "uv sync --extra menubar --extra package" in text
    assert (
        "ANON_PROXY_CODESIGN_IDENTITY=- uv run python packaging/setup_app.py py2app"
        in text
    )
    assert "Set up routing..." in text
    assert "Uninstall routing..." in text
