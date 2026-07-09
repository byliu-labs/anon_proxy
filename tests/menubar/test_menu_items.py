from anon_proxy.menubar import app


def test_menu_config_lines_lists_each_provider():
    lines = app.menu_config_lines("127.0.0.1", 8080)
    joined = "\n".join(lines)
    assert "ANTHROPIC_BASE_URL=http://127.0.0.1:8080/anthropic" in joined
    assert "OPENAI_BASE_URL=http://127.0.0.1:8080/openai" in joined
