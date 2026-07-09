import sys

from anon_proxy.menubar.supervisor import ProxySupervisor


def test_default_cmd_persists_store_and_metrics(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))

    sup = ProxySupervisor()
    cmd = sup._cmd

    assert cmd[:3] == [sys.executable, "-m", "anon_proxy.server"]
    assert "--store" in cmd
    assert "--metrics" in cmd
    assert cmd[cmd.index("--store") + 1].endswith("store.json")
