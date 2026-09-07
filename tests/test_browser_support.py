"""Required CI engines must fail loudly instead of silently losing coverage."""

from types import SimpleNamespace

import pytest
from browser_support import launch_browser


@pytest.mark.parametrize("engine", ["chromium", "webkit"])
def test_ci_engine_launch_failure_is_fatal(monkeypatch, engine):
    monkeypatch.setenv("CI", "true")

    def broken_launch(**kwargs):
        raise RuntimeError("engine startup failed")

    playwright = SimpleNamespace(**{engine: SimpleNamespace(launch=broken_launch)})
    with pytest.raises(RuntimeError, match="engine startup failed"):
        launch_browser(playwright, engine)


def test_unavailable_local_webkit_remains_optional(monkeypatch):
    monkeypatch.delenv("CI", raising=False)

    def broken_launch(**kwargs):
        raise RuntimeError("engine startup failed")

    with pytest.raises(pytest.skip.Exception):
        launch_browser(SimpleNamespace(webkit=SimpleNamespace(launch=broken_launch)), "webkit")
