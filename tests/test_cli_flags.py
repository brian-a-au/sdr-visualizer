"""Phase 9 tests: --exclude-orphans, --max-graph-nodes, --json."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import extract_payload as _embedded_payload

from sdr_visualizer.cli.main import main
from sdr_visualizer.render.color_packs import COLOR_PACK_CODES

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


def test_color_pack_flag_changes_html_identity_but_not_sidecar_payload(tmp_path):
    source = str(FIXTURES / "cja_snapshot_clean.json")
    default_html = tmp_path / "default.html"
    default_json = tmp_path / "default.json"
    blue_html = tmp_path / "blue.html"
    blue_json = tmp_path / "blue.json"

    assert (
        main([source, "--output", str(default_html), "--json", str(default_json), "--quiet"]) == 0
    )
    assert (
        main(
            [
                source,
                "--color-pack",
                "BLUE",
                "--output",
                str(blue_html),
                "--json",
                str(blue_json),
                "--quiet",
            ]
        )
        == 0
    )

    assert 'data-color-pack="default"' in default_html.read_text(encoding="utf-8")
    assert 'data-color-pack="BLUE"' in blue_html.read_text(encoding="utf-8")
    default_payload = json.loads(default_json.read_text(encoding="utf-8"))
    blue_payload = json.loads(blue_json.read_text(encoding="utf-8"))
    default_payload["meta"].pop("generated_at")
    blue_payload["meta"].pop("generated_at")
    assert default_payload == blue_payload


def test_color_pack_help_lists_registry_choices(capsys):
    import pytest

    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "--color-pack" in help_text
    assert "{" + ",".join(COLOR_PACK_CODES) + "}" in help_text


def test_cli_accepts_every_registry_color_pack(tmp_path):
    source = str(FIXTURES / "cja_snapshot_clean.json")

    for code in COLOR_PACK_CODES:
        output = tmp_path / f"{code}.html"
        assert main([source, "--color-pack", code, "--output", str(output), "--quiet"]) == 0
        html = output.read_text(encoding="utf-8")
        assert f'data-color-pack="{code}"' in html
        assert f"Color pack: {code}" in html


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


def test_max_graph_nodes_zero_is_valid_and_enters_payload(tmp_path):
    output = tmp_path / "out.html"

    rc = main(
        [
            str(FIXTURES / "cja_snapshot_clean.json"),
            "--max-graph-nodes",
            "0",
            "--output",
            str(output),
            "--quiet",
        ]
    )

    assert rc == 0
    assert _embedded_payload(output.read_text(encoding="utf-8"))["meta"]["max_graph_nodes"] == 0


def test_negative_max_graph_nodes_is_usage_error_3():
    import pytest

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                str(FIXTURES / "cja_snapshot_clean.json"),
                "--max-graph-nodes",
                "-1",
                "--quiet",
            ]
        )

    assert exc_info.value.code == 3


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
        lambda _payload, *, title=None, color_pack="default": (
            "<!doctype html><title>report</title>"
        ),
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
