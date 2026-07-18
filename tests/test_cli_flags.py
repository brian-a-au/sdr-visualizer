"""Phase 9 tests: --exclude-orphans, --max-graph-nodes, --json."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import extract_payload as _embedded_payload

from sdr_visualizer.cli.main import main

FIXTURES = Path(__file__).parent / "fixtures"


def test_exclude_orphans_flag_threads_to_payload(tmp_path):
    output = tmp_path / "out.html"
    rc = main(
        [
            str(FIXTURES / "cja_snapshot_clean.json"),
            "--exclude-orphans",
            "--output",
            str(output),
            "--quiet",
        ]
    )
    assert rc == 0
    payload = _embedded_payload(output.read_text(encoding="utf-8"))
    assert payload["meta"]["exclude_orphans_default"] is True


def test_default_does_not_set_exclude_orphans(tmp_path):
    output = tmp_path / "out.html"
    rc = main([str(FIXTURES / "cja_snapshot_clean.json"), "--output", str(output), "--quiet"])
    assert rc == 0
    payload = _embedded_payload(output.read_text(encoding="utf-8"))
    assert payload["meta"]["exclude_orphans_default"] is False


def test_max_graph_nodes_threads_to_payload(tmp_path):
    output = tmp_path / "out.html"
    rc = main(
        [
            str(FIXTURES / "cja_snapshot_clean.json"),
            "--max-graph-nodes",
            "250",
            "--output",
            str(output),
            "--quiet",
        ]
    )
    assert rc == 0
    payload = _embedded_payload(output.read_text(encoding="utf-8"))
    assert payload["meta"]["max_graph_nodes"] == 250


def test_json_flag_writes_separate_file_and_reports_both_outputs(tmp_path, capsys):
    html_out = tmp_path / "out.html"
    json_out = tmp_path / "out.json"
    rc = main(
        [
            str(FIXTURES / "cja_snapshot_clean.json"),
            "--output",
            str(html_out),
            "--json",
            str(json_out),
        ]
    )
    assert rc == 0
    assert html_out.exists()
    assert json_out.exists()
    parsed = json.loads(json_out.read_text(encoding="utf-8"))
    assert parsed["meta"]["platform"] == "cja"
    assert parsed["graph"]["edges"]
    err = capsys.readouterr().err
    assert f"sdr-visualizer: wrote {html_out}" in err
    assert f"sdr-visualizer: wrote {json_out}" in err


def test_json_flag_rejects_non_finite_payload(tmp_path, monkeypatch, capsys):
    html_out = tmp_path / "out.html"
    json_out = tmp_path / "out.json"

    monkeypatch.setattr(
        "sdr_visualizer.cli.main.build_payload_with_options",
        lambda _impl, **_options: {"meta": {"component_count": 0}, "score": float("nan")},
    )
    monkeypatch.setattr(
        "sdr_visualizer.cli.main.render_payload",
        lambda _payload, *, title=None: "<!doctype html><title>report</title>",
    )

    rc = main(
        [
            str(FIXTURES / "cja_snapshot_clean.json"),
            "--output",
            str(html_out),
            "--json",
            str(json_out),
            "--quiet",
        ]
    )

    assert rc == 3
    assert html_out.exists()
    assert not json_out.exists()
    assert "payload contains NaN or Infinity" in capsys.readouterr().err


def test_json_flag_write_failure_preserves_html_and_exits_1(tmp_path, capsys):
    html_out = tmp_path / "out.html"
    json_out = tmp_path / "missing" / "out.json"

    rc = main(
        [
            str(FIXTURES / "cja_snapshot_clean.json"),
            "--output",
            str(html_out),
            "--json",
            str(json_out),
            "--quiet",
        ]
    )

    assert rc == 1
    assert html_out.exists()
    assert not json_out.exists()
    err = capsys.readouterr().err
    assert f"sdr-visualizer: could not write {json_out}" in err
    assert "Traceback" not in err
