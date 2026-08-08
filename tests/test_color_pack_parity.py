"""Cross-repository parity checks for the shared color-pack source contract."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from sdr_visualizer.render.color_packs import color_pack_contract_snapshot

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_color_pack_parity.py"

spec = importlib.util.spec_from_file_location("check_color_pack_parity", SCRIPT)
check_color_pack_parity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_color_pack_parity)


def _write_grader_contract(root: Path, contract: object) -> None:
    module = root / "src" / "sdr_grader" / "render" / "color_packs.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        f"def color_pack_contract_snapshot():\n    return {contract!r}\n",
        encoding="utf-8",
    )


def test_matching_local_and_fake_grader_contracts_pass(tmp_path, capsys):
    _write_grader_contract(tmp_path, color_pack_contract_snapshot())

    assert check_color_pack_parity.main(["--grader-root", str(tmp_path)]) == 0
    assert "color-pack contracts match" in capsys.readouterr().out


@pytest.mark.parametrize("field", ["catalog", "source_swatches", "required_roles"])
def test_each_shared_field_drift_is_reported_by_name(tmp_path, capsys, field):
    contract = color_pack_contract_snapshot()
    if field == "catalog":
        contract[field] = ("ADBE", "default", "OMTR", "BLUE")
        contract["source_swatches"] = {
            code: contract["source_swatches"][code] for code in contract[field]
        }
    elif field == "source_swatches":
        contract[field]["default"] = ("#000000",)
    else:
        contract[field] = (*contract[field][:-1], "replacement-role")
    _write_grader_contract(tmp_path, contract)

    assert check_color_pack_parity.main(["--grader-root", str(tmp_path)]) == 1
    error = capsys.readouterr().err
    assert f"color-pack parity mismatch: {field}" in error
    assert "visualizer:" in error
    assert "grader:" in error


def test_missing_grader_checkout_is_a_controlled_failure(tmp_path, capsys):
    missing = tmp_path / "not-checked-out"

    assert check_color_pack_parity.main(["--grader-root", str(missing)]) == 2
    assert "grader checkout not found" in capsys.readouterr().err


@pytest.mark.parametrize(
    "source, expected",
    [
        ("VALUE = 1\n", "does not export color_pack_contract_snapshot"),
        (
            "def color_pack_contract_snapshot():\n    return {'catalog': []}\n",
            "malformed grader color-pack contract",
        ),
        (
            "def color_pack_contract_snapshot():\n    raise RuntimeError('broken')\n",
            "could not read grader color-pack contract",
        ),
    ],
)
def test_malformed_contract_is_a_controlled_failure(tmp_path, capsys, source, expected):
    module = tmp_path / "src" / "sdr_grader" / "render" / "color_packs.py"
    module.parent.mkdir(parents=True)
    module.write_text(source, encoding="utf-8")

    assert check_color_pack_parity.main(["--grader-root", str(tmp_path)]) == 2
    assert expected in capsys.readouterr().err
