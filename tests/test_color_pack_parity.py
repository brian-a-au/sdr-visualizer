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


def _write_grader_contract(root: Path, contract: dict[str, object], *, suffix: str = "") -> None:
    module = root / "src" / "sdr_grader" / "render" / "color_packs.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        "\n".join(
            (
                f"REQUIRED_COLOR_ROLES = {contract['required_roles']!r}",
                f"COLOR_PACK_CODES = {contract['catalog']!r}",
                f"_SOURCE_SWATCHES = {contract['source_swatches']!r}",
                suffix,
            )
        ),
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


def test_top_level_side_effects_are_not_executed(tmp_path, capsys):
    sentinel = tmp_path / "executed"
    suffix = (
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('executed', encoding='utf-8')\n"
        "raise RuntimeError('module code must not execute')"
    )
    _write_grader_contract(
        tmp_path,
        color_pack_contract_snapshot(),
        suffix=suffix,
    )

    assert check_color_pack_parity.main(["--grader-root", str(tmp_path)]) == 0
    assert "color-pack contracts match" in capsys.readouterr().out
    assert not sentinel.exists()


@pytest.mark.parametrize(
    "source, expected",
    [
        ("VALUE = 1\n", "missing literal declarations"),
        (
            "REQUIRED_COLOR_ROLES = ('role',)\n"
            "COLOR_PACK_CODES = ('default',)\n"
            "_SOURCE_SWATCHES = build_swatches()\n",
            "_SOURCE_SWATCHES must be a literal",
        ),
        (
            "REQUIRED_COLOR_ROLES = ('role',)\n"
            "COLOR_PACK_CODES = ('default',)\n"
            "_SOURCE_SWATCHES = {'other': ('#000000',)}\n",
            "source_swatches keys must match catalog order",
        ),
        (
            "REQUIRED_COLOR_ROLES = (\n",
            "could not parse grader color-pack module",
        ),
    ],
)
def test_malformed_contract_is_a_controlled_failure(tmp_path, capsys, source, expected):
    module = tmp_path / "src" / "sdr_grader" / "render" / "color_packs.py"
    module.parent.mkdir(parents=True)
    module.write_text(source, encoding="utf-8")

    assert check_color_pack_parity.main(["--grader-root", str(tmp_path)]) == 2
    assert expected in capsys.readouterr().err
