from anon_proxy.menubar.app import format_target_status
from anon_proxy.routing.scan import ProcInfo


def test_status_line_counts_proxied_and_raw():
    line = format_target_status(
        "claude", enabled=True, procs=[ProcInfo(1, True), ProcInfo(2, False)]
    )
    assert "claude" in line
    assert "2 running" in line
    assert "1 proxied" in line
    assert "restart to apply" in line


def test_status_line_no_instances():
    line = format_target_status("codex", enabled=False, procs=[])
    assert "codex" in line and "not running" in line


def test_status_line_all_proxied_has_no_restart_hint():
    line = format_target_status("claude", enabled=True, procs=[ProcInfo(1, True)])
    assert "restart to apply" not in line


def test_status_line_reports_unavailable_when_ps_env_is_hidden():
    line = format_target_status(
        "claude", enabled=True, procs=[], status_available=False
    )
    assert "status unavailable" in line
