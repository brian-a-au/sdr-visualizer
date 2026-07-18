"""Public module-entry-point behavior."""

from __future__ import annotations

import runpy

import pytest


def test_module_entrypoint_delegates_once_and_preserves_exit_code(monkeypatch):
    calls: list[None] = []

    def fake_main() -> int:
        calls.append(None)
        return 3

    monkeypatch.setattr("sdr_visualizer.cli.main.main", fake_main)

    # Loading the same file under a non-main name proves import is side-effect
    # free; the public ``python -m`` boundary then delegates exactly once.
    runpy.run_module("sdr_visualizer.__main__", run_name="sdr_visualizer._entry_probe")
    assert calls == []

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("sdr_visualizer.__main__", run_name="__main__")

    assert exc_info.value.code == 3
    assert calls == [None]
