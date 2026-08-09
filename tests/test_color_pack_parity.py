"""Cross-repository parity checks for color-pack commits, never worktrees."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

from sdr_visualizer.render.color_packs import color_pack_contract_snapshot

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_color_pack_parity.py"

spec = importlib.util.spec_from_file_location("check_color_pack_parity", SCRIPT)
check_color_pack_parity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_color_pack_parity)


def _module_path(root: Path, label: str) -> Path:
    package = "sdr_visualizer" if label == "visualizer" else "sdr_grader"
    return root / "src" / package / "render" / "color_packs.py"


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _init_repo(root: Path) -> None:
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Parity Test")
    _git(root, "config", "user.email", "parity@example.invalid")


def _commit(root: Path, message: str) -> str:
    _git(root, "add", ".")
    _git(root, "commit", "-qm", message)
    return _git(root, "rev-parse", "HEAD")


def _write_contract(
    root: Path, label: str, contract: dict[str, object], *, suffix: str = ""
) -> None:
    module = _module_path(root, label)
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text(
        "\n".join(
            (
                f"REQUIRED_COLOR_ROLES = {contract['required_roles']!r}",
                f"COLOR_PACK_CODES = {contract['catalog']!r}",
                f"_SOURCE_SWATCHES = {contract['source_swatches']!r}",
                f"TEXT_CONTRAST_PAIRS = {contract['text_contrast_pairs']!r}",
                f"NON_TEXT_CONTRAST_PAIRS = {contract['non_text_contrast_pairs']!r}",
                suffix,
            )
        ),
        encoding="utf-8",
    )


def _matching_repos(tmp_path: Path) -> tuple[Path, str, Path, str]:
    visualizer = tmp_path / "visualizer"
    grader = tmp_path / "grader"
    _init_repo(visualizer)
    _init_repo(grader)
    contract = color_pack_contract_snapshot()
    _write_contract(visualizer, "visualizer", contract)
    _write_contract(grader, "grader", contract)
    return (
        visualizer,
        _commit(visualizer, "visualizer contract"),
        grader,
        _commit(grader, "grader contract"),
    )


def _args(visualizer: Path, visualizer_sha: str, grader: Path, grader_sha: str) -> list[str]:
    return [
        "--visualizer-root",
        str(visualizer),
        "--visualizer-sha",
        visualizer_sha,
        "--grader-root",
        str(grader),
        "--grader-sha",
        grader_sha,
    ]


def test_matching_commit_blobs_pass_even_when_worktrees_drift(tmp_path, capsys):
    visualizer, visualizer_sha, grader, grader_sha = _matching_repos(tmp_path)
    _write_contract(
        grader,
        "grader",
        {
            "catalog": ("drift",),
            "source_swatches": {"drift": ("#000000",)},
            "required_roles": ("role",),
            "text_contrast_pairs": (("role", "role"),),
            "non_text_contrast_pairs": (("role", "role"),),
        },
    )

    assert check_color_pack_parity.main(_args(visualizer, visualizer_sha, grader, grader_sha)) == 0
    assert "color-pack contracts match" in capsys.readouterr().out


@pytest.mark.parametrize(
    "field",
    [
        "catalog",
        "source_swatches",
        "required_roles",
        "text_contrast_pairs",
        "non_text_contrast_pairs",
    ],
)
def test_each_shared_field_drift_is_reported_from_the_pinned_blobs(tmp_path, capsys, field):
    visualizer, visualizer_sha, grader, _grader_sha = _matching_repos(tmp_path)
    contract = color_pack_contract_snapshot()
    if field == "catalog":
        contract[field] = ("ADBE", "default", "OMTR", "BLUE")
        contract["source_swatches"] = {
            code: contract["source_swatches"][code] for code in contract[field]
        }
    elif field == "source_swatches":
        contract[field]["default"] = ("#000000",)
    elif field == "required_roles":
        contract[field] = (contract[field][1], contract[field][0], *contract[field][2:])
    else:
        contract[field] = (*contract[field][:-1], tuple(reversed(contract[field][-1])))
    _write_contract(grader, "grader", contract)
    grader_sha = _commit(grader, f"drift {field}")

    assert check_color_pack_parity.main(_args(visualizer, visualizer_sha, grader, grader_sha)) == 1
    error = capsys.readouterr().err
    assert f"color-pack parity mismatch: {field}" in error
    assert "visualizer:" in error
    assert "grader:" in error


def test_non_git_checkout_is_a_controlled_failure(tmp_path, capsys):
    visualizer, visualizer_sha, grader, grader_sha = _matching_repos(tmp_path)
    non_git = tmp_path / "not-a-git-repository"
    non_git.mkdir()

    assert check_color_pack_parity.main(_args(non_git, visualizer_sha, grader, grader_sha)) == 2
    assert "visualizer checkout is not a Git repository" in capsys.readouterr().err


def test_missing_sibling_checkout_is_a_controlled_failure(tmp_path, capsys):
    visualizer, visualizer_sha, _grader, grader_sha = _matching_repos(tmp_path)
    missing = tmp_path / "missing-grader-checkout"

    assert check_color_pack_parity.main(_args(visualizer, visualizer_sha, missing, grader_sha)) == 2
    assert "grader checkout not found" in capsys.readouterr().err


@pytest.mark.parametrize("sha", ["short", "f" * 40])
def test_bad_or_missing_commit_sha_is_a_controlled_failure(tmp_path, capsys, sha):
    visualizer, visualizer_sha, grader, grader_sha = _matching_repos(tmp_path)

    assert check_color_pack_parity.main(_args(visualizer, visualizer_sha, grader, sha)) == 2
    assert "grader" in capsys.readouterr().err


def test_missing_registry_blob_is_a_controlled_failure(tmp_path, capsys):
    visualizer, visualizer_sha, grader, _grader_sha = _matching_repos(tmp_path)
    _module_path(grader, "grader").unlink()
    grader_sha = _commit(grader, "remove registry")

    assert check_color_pack_parity.main(_args(visualizer, visualizer_sha, grader, grader_sha)) == 2
    assert "grader color-pack module not found in commit" in capsys.readouterr().err


def test_pinned_blob_never_executes_top_level_side_effects(tmp_path, capsys):
    visualizer, visualizer_sha, grader, _grader_sha = _matching_repos(tmp_path)
    sentinel = tmp_path / "executed"
    _write_contract(
        grader,
        "grader",
        color_pack_contract_snapshot(),
        suffix=(
            "from pathlib import Path\n"
            f"Path({str(sentinel)!r}).write_text('executed', encoding='utf-8')\n"
            "raise RuntimeError('module code must not execute')"
        ),
    )
    grader_sha = _commit(grader, "side effect")

    assert check_color_pack_parity.main(_args(visualizer, visualizer_sha, grader, grader_sha)) == 0
    assert "color-pack contracts match" in capsys.readouterr().out
    assert not sentinel.exists()


def test_duplicate_literal_declaration_is_a_controlled_failure(tmp_path, capsys):
    visualizer, visualizer_sha, grader, _grader_sha = _matching_repos(tmp_path)
    _write_contract(
        grader,
        "grader",
        color_pack_contract_snapshot(),
        suffix="COLOR_PACK_CODES = ('duplicate',)\n",
    )
    grader_sha = _commit(grader, "duplicate declaration")

    assert check_color_pack_parity.main(_args(visualizer, visualizer_sha, grader, grader_sha)) == 2
    assert "duplicate literal declaration COLOR_PACK_CODES" in capsys.readouterr().err


@pytest.mark.parametrize(
    "source, expected",
    [
        ("VALUE = 1\n", "missing literal declarations"),
        (
            "REQUIRED_COLOR_ROLES = ('role',)\n"
            "COLOR_PACK_CODES = ('default',)\n"
            "_SOURCE_SWATCHES = build_swatches()\n"
            "TEXT_CONTRAST_PAIRS = (('role', 'role'),)\n"
            "NON_TEXT_CONTRAST_PAIRS = (('role', 'role'),)\n",
            "_SOURCE_SWATCHES must be a literal",
        ),
        (
            "REQUIRED_COLOR_ROLES = ('role',)\n"
            "COLOR_PACK_CODES = ('default',)\n"
            "_SOURCE_SWATCHES = {'other': ('#000000',)}\n"
            "TEXT_CONTRAST_PAIRS = (('role', 'role'),)\n"
            "NON_TEXT_CONTRAST_PAIRS = (('role', 'role'),)\n",
            "source_swatches keys must match catalog order",
        ),
    ],
)
def test_nonliteral_or_malformed_pinned_blob_is_a_controlled_failure(
    tmp_path, capsys, source, expected
):
    visualizer, visualizer_sha, grader, _grader_sha = _matching_repos(tmp_path)
    module = _module_path(grader, "grader")
    module.write_text(source, encoding="utf-8")
    grader_sha = _commit(grader, "malformed registry")

    assert check_color_pack_parity.main(_args(visualizer, visualizer_sha, grader, grader_sha)) == 2
    assert expected in capsys.readouterr().err
