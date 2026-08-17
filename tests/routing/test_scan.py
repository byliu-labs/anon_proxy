from anon_proxy.routing.scan import ProcInfo, classify_instances


def test_classifies_proxied_vs_raw_by_env():
    lines = [
        "  501 /usr/local/bin/claude --foo ANTHROPIC_BASE_URL=http://127.0.0.1:51843/anthropic",
        "  777 /usr/local/bin/claude --bar",
        "  888 /usr/bin/vim notes.txt",
    ]
    got = classify_instances("claude", "ANTHROPIC_BASE_URL", ps_lines=lines)
    assert ProcInfo(pid=501, proxied=True) in got
    assert ProcInfo(pid=777, proxied=False) in got
    assert all(p.pid != 888 for p in got)


def test_public_url_env_does_not_count_as_proxied():
    lines = ["  9 /usr/local/bin/claude ANTHROPIC_BASE_URL=https://api.anthropic.com"]
    got = classify_instances("claude", "ANTHROPIC_BASE_URL", ps_lines=lines)
    assert got == [ProcInfo(pid=9, proxied=False)]


def test_empty_when_no_instances():
    assert classify_instances("codex", "OPENAI_BASE_URL", ps_lines=[]) == []
