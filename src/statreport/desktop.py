"""
desktop.py — run the local web GUI inside a NATIVE OS window (pywebview).

The Flask app is served on a loopback port from a DAEMON thread (so the process
dies when the window closes), and the window is opened on the MAIN thread — which
is mandatory for the macOS Cocoa/WKWebView and Windows WebView2 backends.

If no webview backend is available (e.g. a PyInstaller build where WebView2 didn't
bundle cleanly), it falls back to opening the default browser. SSE/EventSource and
fetch to 127.0.0.1 work unchanged inside WKWebView/WebView2 — the window loads from
the same origin, so there are no CORS changes.
"""

from __future__ import annotations

import socket
import threading
import time


def _wait(port: int, host: str = "127.0.0.1", timeout: float = 12.0) -> bool:
    """Block until the server accepts a connection on `port`, or time out."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection((host, port), 0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def run_desktop(app, find_free_port, host: str = "127.0.0.1", title: str = "StatReport") -> None:
    """Serve `app` on a free loopback port and open it in a native window (blocking).

    `app`            : the WSGI app (Flask) exposing `.run(host, port, threaded)`.
    `find_free_port` : callable returning an available port.
    """
    port = find_free_port()
    threading.Thread(
        target=lambda: app.run(host=host, port=port, threaded=True),
        daemon=True,
    ).start()
    _wait(port, host)
    url = f"http://{host}:{port}/"

    try:
        import webview  # pywebview
        print(f"{title}: opening desktop window at {url}")
        webview.create_window(title, url, width=1240, height=900, min_size=(900, 640))
        webview.start()  # MUST run on the main thread; blocks until the window closes
    except Exception as exc:  # no webview backend -> graceful browser fallback
        import webbrowser
        print(f"{title} running (browser fallback: {type(exc).__name__}): {url}")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
