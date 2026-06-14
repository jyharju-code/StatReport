"""app_main.py — entry point for the standalone app (PyInstaller).

main() opens the GUI in a native desktop window (pywebview), falling back to the
browser if no webview backend is available.
"""

from statreport.server import main

if __name__ == "__main__":
    main()
