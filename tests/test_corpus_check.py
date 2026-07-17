"""Corpus sweep script tests (loaded via importlib; scripts/ is not a package)."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"

spec = importlib.util.spec_from_file_location("corpus_check", REPO / "scripts" / "corpus_check.py")
corpus_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(corpus_check)


def _build_corpus(tmp_path):
    corpus = tmp_path / "corpus"
    (corpus / "org-a").mkdir(parents=True)
    shutil.copy(FIXTURES / "cja_snapshot_clean.json", corpus / "org-a" / "cja.json")
    shutil.copy(FIXTURES / "aa_snapshot_clean.json", corpus / "aa.json")
    return corpus


def test_clean_corpus_sweeps_ok(tmp_path, capsys):
    corpus = _build_corpus(tmp_path)
    rc = corpus_check.sweep(corpus, check_budgets=False)
    assert rc == 0
    out = capsys.readouterr().out
    assert out.count("OK") == 2
    assert "0 failed" in out


def test_recursive_discovery_and_failure_reporting(tmp_path, capsys):
    corpus = _build_corpus(tmp_path)
    (corpus / "org-a" / "broken.json").write_text("{not json", encoding="utf-8")
    nan_snap = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))
    nan_snap["calculated_metrics"]["metrics"][0]["complexity_score"] = float("nan")
    (corpus / "nan.json").write_text(json.dumps(nan_snap), encoding="utf-8")
    rc = corpus_check.sweep(corpus, check_budgets=False)
    assert rc == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "broken.json" in out
    assert "nan.json" in out
    assert "2 failed" in out


def test_literal_u003c_text_in_snapshot_sweeps_ok(tmp_path):
    # A field whose text literally contains a backslash-u003c sequence (six
    # characters) is embedded in the payload with the backslash doubled. The
    # sweep must parse the embedded payload exactly as the browser does —
    # naively un-escaping the u003c escape via string replacement corrupts
    # the doubled form into an invalid backslash-then-open-angle escape and
    # reports a valid snapshot as a false FAIL.
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    snap = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))
    snap["metrics"][0]["description"] = "renders a literal \\u003c escape"
    (corpus / "u003c.json").write_text(json.dumps(snap), encoding="utf-8")
    rc = corpus_check.sweep(corpus, check_budgets=False)
    assert rc == 0


def test_budget_flag_reports_tier(tmp_path, capsys):
    corpus = _build_corpus(tmp_path)
    rc = corpus_check.sweep(corpus, check_budgets=True)
    assert rc == 0
    assert "MB" in capsys.readouterr().out


def test_missing_directory_is_usage_error(tmp_path):
    rc = corpus_check.main([str(tmp_path / "nope")])
    assert rc == 2
