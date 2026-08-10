import sys


def _dispatch(argv: list[str] | None = None) -> None:
    """Route the frozen-bundle binary to the server or the menu-bar app.

    A PyInstaller bundle has a single executable, so the proxy supervisor and
    launch agent re-invoke it with a ``--run-server`` sentinel when they want
    the server rather than another menu-bar instance (see
    ``supervisor.server_command``). Anything else is the menu-bar app.
    """
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    if argv and argv[0] == "--run-server":
        from anon_proxy.server import main as server_main

        server_main(argv[1:])
        return
    from anon_proxy.menubar.app import main

    main(argv)


if __name__ == "__main__":
    _dispatch()
