"""Browser launch policy shared by the required functional engine suites."""

import os
from pathlib import Path

import pytest


def launch_browser(playwright, engine):
    try:
        return getattr(playwright, engine).launch(headless=True)
    except Exception:
        if os.environ.get("CI"):
            raise
        system_chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        if engine == "chromium" and system_chrome.is_file():
            try:
                return playwright.chromium.launch(headless=True, executable_path=str(system_chrome))
            except Exception as exc:
                pytest.skip(f"chromium not available: {exc}")
        pytest.skip(f"{engine} not available; install the Playwright browsers")
