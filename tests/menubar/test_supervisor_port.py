import socket

from anon_proxy.menubar.supervisor import ProxySupervisor
from anon_proxy.routing.controller import RoutingController
from anon_proxy.routing.state import RoutingState, load_state


def test_free_port_is_bindable():
    port = ProxySupervisor.free_port()
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))


def test_controller_records_supervisor_port(tmp_path, monkeypatch):
    monkeypatch.setenv("ANON_PROXY_HOME", str(tmp_path))
    c = RoutingController(RoutingState(enabled=True))
    c.set_port(ProxySupervisor.free_port())
    assert load_state().port is not None
