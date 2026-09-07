"""Public lineage command contracts, using saved synthetic input."""

from pathlib import Path

import pytest

from sdr_visualizer.cli import lineage

FIXTURE = Path(__file__).parent / "fixtures" / "cja_lineage_shared.json"


def test_saved_report_and_help(tmp_path, capsys):
    output = tmp_path / "lineage.html"
    assert lineage.main(["--saved", str(FIXTURE), "--output", str(output)]) == 0
    assert 'id="sdr-lineage-data"' in output.read_text()
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(SystemExit) as caught:
        lineage.main(["--help"])
    assert caught.value.code == 0
    assert "--output" in capsys.readouterr().out


def test_alias_preserves_source(tmp_path):
    source = tmp_path / "source.json"
    source.write_bytes(FIXTURE.read_bytes())
    assert lineage.main(["--saved", str(source), "--output", str(source)]) == 3
    assert source.read_bytes() == FIXTURE.read_bytes()


@pytest.mark.parametrize(
    "args",
    [[], ["--live"], ["--saved", "x", "--profile", "x"], ["--saved", "x", "--scope-label", ""]],
)
def test_invalid_arguments_are_content_free(args, capsys):
    with pytest.raises(SystemExit) as caught:
        lineage.main(args)
    assert caught.value.code == 2
    assert "Traceback" not in capsys.readouterr().err


def test_bad_saved_input_has_actionable_private_error(tmp_path, capsys):
    source = tmp_path / "PRIVATE_CANARY.json"
    source.write_text("PRIVATE_CANARY")
    assert lineage.main(["--saved", str(source), "--output", str(tmp_path / "out.html")]) == 3
    error = capsys.readouterr().err
    assert "invalid-json" in error
    assert "PRIVATE_CANARY" not in error


def test_aa_snapshot_is_rejected(tmp_path, capsys):
    source = FIXTURE.with_name("aa_snapshot_messy.json")
    assert source.is_file()
    assert lineage.main(["--saved", str(source), "--output", str(tmp_path / "out.html")]) == 3
    error = capsys.readouterr().err
    assert "invalid-structure" in error
    assert "not AA or component snapshots" in error


def test_live_route_and_runtime_failures(tmp_path, monkeypatch, capsys):
    from sdr_visualizer.cli.lineage_output import LineageOutputFailure, LineageOutputFailureCode

    args = [
        "--live",
        "--binary",
        "/tmp/cja_auto_sdr",
        "--config-file",
        "/tmp/config.json",
        "--output",
        str(tmp_path / "out.html"),
        "--quiet",
    ]
    calls = []
    monkeypatch.setattr(lineage, "acquire_live", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setattr(lineage, "render", lambda *a, **kw: "report")
    assert lineage.main(args) == 0
    assert calls[0][1]["config_file"] == Path("/tmp/config.json")
    assert capsys.readouterr().err == ""
    monkeypatch.setattr(
        lineage,
        "write_lineage_output",
        lambda *a, **kw: LineageOutputFailure(LineageOutputFailureCode.WRITE_FAILED),
    )
    assert lineage.main(args) == 1

    def fail(*a, **kw):
        raise ValueError("PRIVATE_CANARY")

    monkeypatch.setattr(lineage, "render", fail)
    assert lineage.main(args) == 1
    assert "PRIVATE_CANARY" not in capsys.readouterr().err
    with pytest.raises(SystemExit) as caught:
        lineage.main(["--live", "--binary", "/tmp/tool", "--config-file", "relative"])
    assert caught.value.code == 2


def test_module_version(monkeypatch, capsys):
    import runpy
    import sys

    monkeypatch.delitem(sys.modules, "sdr_visualizer.cli.lineage", raising=False)
    monkeypatch.setattr(sys, "argv", ["cja-lineage", "--version"])
    with pytest.raises(SystemExit) as caught:
        runpy.run_module("sdr_visualizer.cli.lineage", run_name="__main__")
    assert caught.value.code == 0
    assert "cja-lineage 1.1.0" in capsys.readouterr().out
