"""Regression tests for output destinations that alias snapshot inputs."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sdr_visualizer.cli.main import _paths_alias, main
from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.input.loader import list_snapshot_candidates


def _snapshot(metric_id: str = "metrics/m1") -> dict:
    return {
        "metadata": {"Data View ID": "dv_output_safety", "Data View Name": "Safety"},
        "data_view": {"id": "dv_output_safety"},
        "metrics": [{"id": metric_id, "name": metric_id, "description": "d"}],
        "dimensions": [],
        "segments": {"segments": []},
        "calculated_metrics": {"metrics": []},
    }


def _write_snapshot(path: Path, metric_id: str = "metrics/m1") -> bytes:
    raw = json.dumps(_snapshot(metric_id)).encode()
    path.write_bytes(raw)
    return raw


def test_primary_input_cannot_be_overwritten_by_html_output(tmp_path, capsys):
    source = tmp_path / "source.json"
    original = _write_snapshot(source)
    sidecar = tmp_path / "sidecar.json"

    rc = main(
        [
            str(source),
            "--output",
            str(source),
            "--json",
            str(sidecar),
            "--quiet",
        ]
    )

    assert rc == 3
    assert source.read_bytes() == original
    assert not sidecar.exists()
    assert "HTML output aliases primary input" in capsys.readouterr().err


def test_invalid_color_pack_preserves_existing_html_and_creates_no_json(tmp_path, capsys):
    source = tmp_path / "source.json"
    _write_snapshot(source)
    html_output = tmp_path / "report.html"
    original_html = b"existing report"
    html_output.write_bytes(original_html)
    json_output = tmp_path / "report.json"

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                str(source),
                "--color-pack",
                "adbe",
                "--output",
                str(html_output),
                "--json",
                str(json_output),
                "--quiet",
            ]
        )

    assert exc_info.value.code == 3
    assert html_output.read_bytes() == original_html
    assert not json_output.exists()
    err = capsys.readouterr().err
    assert "invalid choice" in err
    assert "default" in err and "ADBE" in err and "OMTR" in err and "BLUE" in err


def test_primary_input_cannot_be_overwritten_by_json_output(tmp_path, capsys):
    source = tmp_path / "source.json"
    original = _write_snapshot(source)
    html_output = tmp_path / "report.html"

    rc = main(
        [
            str(source),
            "--output",
            str(html_output),
            "--json",
            str(source),
            "--quiet",
        ]
    )

    assert rc == 3
    assert source.read_bytes() == original
    assert not html_output.exists()
    assert "JSON output aliases primary input" in capsys.readouterr().err


def test_html_and_json_outputs_must_be_distinct_before_either_write(tmp_path, capsys):
    source = tmp_path / "source.json"
    _write_snapshot(source)
    output = tmp_path / "report.json"

    rc = main([str(source), "--output", str(output), "--json", str(output), "--quiet"])

    assert rc == 3
    assert not output.exists()
    assert "HTML output aliases JSON output" in capsys.readouterr().err


@pytest.mark.parametrize("alias_kind", ["symlink", "symlinked-parent", "hardlink"])
def test_filesystem_aliases_to_primary_input_are_rejected(tmp_path, capsys, alias_kind):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    source = real_dir / "source.json"
    original = _write_snapshot(source)

    if alias_kind == "symlink":
        output = tmp_path / "output.html"
        output.symlink_to(source)
    elif alias_kind == "symlinked-parent":
        alias_dir = tmp_path / "alias"
        alias_dir.symlink_to(real_dir, target_is_directory=True)
        output = alias_dir / "source.json"
    else:
        output = tmp_path / "output.html"
        os.link(source, output)

    rc = main([str(source), "--output", str(output), "--quiet"])

    assert rc == 3
    assert source.read_bytes() == original
    assert "HTML output aliases primary input" in capsys.readouterr().err


def test_compare_baseline_cannot_be_overwritten(tmp_path, capsys):
    baseline = tmp_path / "baseline.json"
    original = _write_snapshot(baseline, "metrics/old")
    primary = tmp_path / "primary.json"
    _write_snapshot(primary, "metrics/new")

    rc = main(
        [
            str(primary),
            "--compare-to",
            str(baseline),
            "--output",
            str(baseline),
            "--quiet",
        ]
    )

    assert rc == 3
    assert baseline.read_bytes() == original
    assert "HTML output aliases baseline input" in capsys.readouterr().err


@pytest.mark.parametrize(
    "protected_name, protected_content",
    [
        ("untimestamped.json", b"not even json"),
        ("snapshot_2026-01-01T00-00-00.json", b"not even json"),
    ],
)
def test_directory_candidates_are_protected_even_when_skipped_or_corrupt(
    tmp_path, capsys, protected_name, protected_content
):
    directory = tmp_path / "snapshots"
    directory.mkdir()
    _write_snapshot(directory / "snapshot_2026-02-01T00-00-00.json")
    protected = directory / protected_name
    protected.write_bytes(protected_content)

    rc = main([str(directory), "--output", str(protected), "--quiet"])

    assert rc == 3
    assert protected.read_bytes() == protected_content
    assert "HTML output aliases primary input" in capsys.readouterr().err


def test_trend_candidate_is_protected_even_when_omitted_by_cap(tmp_path, capsys):
    directory = tmp_path / "snapshots"
    directory.mkdir()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    protected = directory / "snapshot_2026-01-01T00-00-00.json"
    original = b""
    for index in range(61):
        stamp = (start + timedelta(hours=index)).strftime("%Y-%m-%dT%H-%M-%S")
        path = directory / f"snapshot_{stamp}.json"
        raw = _write_snapshot(path, f"metrics/m{index}")
        if index == 0:
            protected = path
            original = raw

    rc = main([str(directory), "--trend", "--output", str(protected), "--quiet"])

    assert rc == 3
    assert protected.read_bytes() == original
    assert "HTML output aliases primary input" in capsys.readouterr().err


def test_candidate_discovery_error_is_an_input_error(tmp_path, monkeypatch, capsys):
    directory = tmp_path / "snapshots"
    directory.mkdir()

    def fail_discovery(_self, _pattern):
        raise OSError("discovery unavailable")

    monkeypatch.setattr(Path, "glob", fail_discovery)

    rc = main([str(directory), "--output", str(tmp_path / "report.html"), "--quiet"])

    assert rc == 3
    assert "could not inspect snapshot directory" in capsys.readouterr().err


def test_identity_error_is_content_free_domain_error(tmp_path, monkeypatch):
    left = tmp_path / "left"
    right = tmp_path / "right"

    def fail_identity(_self, *, strict=False):
        raise OSError("hostile path detail")

    monkeypatch.setattr(Path, "resolve", fail_identity)

    with pytest.raises(
        InvalidSnapshotError, match="could not verify output destination identity"
    ) as exc:
        _paths_alias(left, right)

    assert "hostile path detail" not in str(exc.value)


def test_candidate_listing_returns_every_sorted_json_path(tmp_path):
    directory = tmp_path / "snapshots"
    directory.mkdir()
    assert list_snapshot_candidates(directory) == []

    expected = [directory / "a.json", directory / "b.json"]
    for path in reversed(expected):
        path.write_text("{}", encoding="utf-8")
    (directory / "ignored.txt").write_text("{}", encoding="utf-8")

    assert list_snapshot_candidates(directory) == expected
