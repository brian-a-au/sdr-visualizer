"""Series loader tests (0.5.0 trend mode)."""

from __future__ import annotations

import json

import pytest

from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.input.series import TREND_SNAPSHOT_CAP, list_snapshot_series


def _write(directory, name, payload):
    p = directory / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_series_ordered_oldest_to_newest(tmp_path):
    _write(tmp_path, "snapshot_2026-03-01T00-00-00.json", {"n": 2})
    _write(tmp_path, "snapshot_2026-01-01T00-00-00.json", {"n": 1})
    _write(tmp_path, "snapshot_2026-05-01T00-00-00.json", {"n": 3})
    entries, capped = list_snapshot_series(str(tmp_path))
    assert [s["n"] for s, _ in entries] == [1, 2, 3]
    assert capped is False
    assert entries[0][1].endswith("snapshot_2026-01-01T00-00-00.json")


def test_at_bounds_the_window_end(tmp_path):
    _write(tmp_path, "snapshot_2026-01-01T00-00-00.json", {"n": 1})
    _write(tmp_path, "snapshot_2026-03-01T00-00-00.json", {"n": 2})
    _write(tmp_path, "snapshot_2026-05-01T00-00-00.json", {"n": 3})
    entries, _ = list_snapshot_series(str(tmp_path), at="2026-04-01")
    assert [s["n"] for s, _ in entries] == [1, 2]


def test_unparseable_snapshot_skipped_with_warning(tmp_path, capsys):
    _write(tmp_path, "snapshot_2026-01-01T00-00-00.json", {"n": 1})
    (tmp_path / "snapshot_2026-02-01T00-00-00.json").write_text("{not json", encoding="utf-8")
    _write(tmp_path, "snapshot_2026-03-01T00-00-00.json", {"n": 3})
    entries, _ = list_snapshot_series(str(tmp_path))
    assert [s["n"] for s, _ in entries] == [1, 3]
    err = capsys.readouterr().err
    assert "skipping snapshot_2026-02-01T00-00-00.json" in err


def test_cap_keeps_most_recent_and_warns(tmp_path, capsys):
    # Hours/minutes kept valid for any i (i=60+ as a minute would fail
    # timestamp parsing and silently change what this test exercises).
    for i in range(TREND_SNAPSHOT_CAP + 3):
        _write(tmp_path, f"snapshot_2026-01-01T{i // 60:02d}-{i % 60:02d}-00.json", {"n": i})
    entries, capped = list_snapshot_series(str(tmp_path))
    assert capped is True
    assert len(entries) == TREND_SNAPSHOT_CAP
    assert entries[0][0]["n"] == 3  # the 3 oldest were dropped
    assert entries[-1][0]["n"] == TREND_SNAPSHOT_CAP + 2
    assert "capped at 60 snapshots; dropped 3" in capsys.readouterr().err


def test_malformed_recent_files_do_not_consume_cap_slots(tmp_path):
    # Newest files are malformed; older files are valid. The cap must count
    # parseable snapshots, not files, so the valid older snapshots survive
    # instead of being starved out of the window.
    _write(tmp_path, "snapshot_2026-01-01T00-00-00.json", {"n": 1})
    _write(tmp_path, "snapshot_2026-02-01T00-00-00.json", {"n": 2})
    (tmp_path / "snapshot_2026-03-01T00-00-00.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "snapshot_2026-04-01T00-00-00.json").write_text("{not json", encoding="utf-8")
    entries, capped = list_snapshot_series(str(tmp_path), cap=2)
    assert [s["n"] for s, _ in entries] == [1, 2]
    assert capped is False


def test_cap_flag_ignores_unparseable_older_files(tmp_path, capsys):
    # The newest `cap` snapshots are valid; every older file is malformed.
    # No parseable history is actually omitted, so the window must not report
    # as capped (dropped/capped count parseable snapshots, not files).
    _write(tmp_path, "snapshot_2026-03-01T00-00-00.json", {"n": 3})
    _write(tmp_path, "snapshot_2026-04-01T00-00-00.json", {"n": 4})
    (tmp_path / "snapshot_2026-01-01T00-00-00.json").write_text("{bad", encoding="utf-8")
    (tmp_path / "snapshot_2026-02-01T00-00-00.json").write_text("{bad", encoding="utf-8")
    entries, capped = list_snapshot_series(str(tmp_path), cap=2)
    assert [s["n"] for s, _ in entries] == [3, 4]
    assert capped is False
    assert "capped at" not in capsys.readouterr().err


def test_fewer_than_two_parseable_raises(tmp_path):
    _write(tmp_path, "snapshot_2026-01-01T00-00-00.json", {"n": 1})
    with pytest.raises(InvalidSnapshotError, match="at least 2"):
        list_snapshot_series(str(tmp_path))


def test_non_directory_and_stdin_raise(tmp_path):
    f = _write(tmp_path, "snap.json", {"n": 1})
    with pytest.raises(InvalidSnapshotError, match="directory"):
        list_snapshot_series(str(f))
    with pytest.raises(InvalidSnapshotError, match="directory"):
        list_snapshot_series("-")


def test_bad_at_value_raises(tmp_path):
    _write(tmp_path, "snapshot_2026-01-01T00-00-00.json", {"n": 1})
    _write(tmp_path, "snapshot_2026-02-01T00-00-00.json", {"n": 2})
    with pytest.raises(InvalidSnapshotError, match="not a recognized timestamp"):
        list_snapshot_series(str(tmp_path), at="not-a-date")


def test_unstamped_file_dropped_from_mixed_directory_warns(tmp_path, capsys):
    _write(tmp_path, "snapshot_2026-01-01T00-00-00.json", {"n": 1})
    _write(tmp_path, "snapshot_2026-02-01T00-00-00.json", {"n": 2})
    _write(tmp_path, "plain.json", {"n": 99})
    entries, _ = list_snapshot_series(str(tmp_path))
    assert len(entries) == 2
    err = capsys.readouterr().err
    assert "skipping plain.json: no filename timestamp while other snapshots have one" in err


def test_mtime_fallback_when_no_filename_timestamps(tmp_path):
    import os
    import time

    a = _write(tmp_path, "alpha.json", {"n": 1})
    b = _write(tmp_path, "beta.json", {"n": 2})
    now = time.time()
    os.utime(a, (now - 100, now - 100))
    os.utime(b, (now, now))
    entries, _ = list_snapshot_series(str(tmp_path))
    assert [s["n"] for s, _ in entries] == [1, 2]
