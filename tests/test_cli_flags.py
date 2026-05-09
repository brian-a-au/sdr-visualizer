"""Phase 9 tests: --exclude-orphans, --max-graph-nodes, --json."""

from __future__ import annotations

import json
import re
from pathlib import Path

from sdr_visualizer.cli.main import main

FIXTURES = Path(__file__).parent / "fixtures"


def _embedded_payload(html: str) -> dict:
    match = re.search(
        r'<script id="sdr-data" type="application/json">(?P<json>.*?)</script>',
        html,
        re.DOTALL,
    )
    return json.loads(match.group("json"))


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


def test_json_flag_writes_separate_file(tmp_path):
    html_out = tmp_path / "out.html"
    json_out = tmp_path / "out.json"
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
    assert rc == 0
    assert html_out.exists()
    assert json_out.exists()
    parsed = json.loads(json_out.read_text(encoding="utf-8"))
    assert parsed["meta"]["platform"] == "cja"
    assert parsed["graph"]["nodes"]
