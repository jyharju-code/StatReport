"""Tests for the desktop window helper (headless-safe — no webview backend needed)."""

import socket

from statreport.desktop import _wait


def test_wait_false_for_dead_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()  # nothing is listening now
    assert _wait(port, timeout=0.5) is False


def test_wait_true_for_live_port():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert _wait(port, timeout=2.0) is True
    finally:
        srv.close()
