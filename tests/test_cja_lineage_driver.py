"""Private CJA lineage driver and owner-only output contracts."""

from __future__ import annotations

import os
import stat

import pytest

import scripts.generate_cja_lineage_poc as driver
import sdr_visualizer.cli.lineage_output as lineage_output
from sdr_visualizer.analysis.lineage_layout import LineageLayoutError
from sdr_visualizer.input.lineage_discovery import (
    LineageDiscoveryFailure,
    LineageDiscoveryFailureCode,
)

CANARY = "HOSTILE_SELECTOR_CANARY_31f4"


def _unexpected(*_args, **_kwargs):
    raise AssertionError("acquisition must not run")


def test_saved_and_live_success_use_exact_boundaries(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    saved = tmp_path / "saved.json"
    saved.write_text("{}", encoding="utf-8")
    binary = tmp_path / "cja_auto_sdr"
    binary.write_text("binary", encoding="utf-8")
    binary.chmod(0o700)
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    topology = object()
    calls: list[tuple] = []

    def fake_saved(path, *, scope_label):
        calls.append(("saved", path, scope_label))
        return topology

    def fake_live(executable, *, scope_label, profile, config_file=None):
        calls.append(("live", executable, scope_label, profile, config_file))
        return topology

    def fake_render(value, *, title, color_pack="default"):
        calls.append(("render", value, title, color_pack))
        return "<html>complete</html>"

    monkeypatch.setattr(driver, "acquire_saved", fake_saved)
    monkeypatch.setattr(driver, "acquire_live", fake_live)
    monkeypatch.setattr(driver, "render", fake_render)

    assert driver.main(["--saved", str(saved), "--scope-label", "Saved scope"]) == 0
    output = tmp_path / driver.OUTPUT_FILENAME
    assert output.read_text(encoding="utf-8") == "<html>complete</html>"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    output.unlink()

    assert (
        driver.main(
            [
                "--live",
                "--binary",
                str(binary),
                "--config-file",
                str(config),
                "--color-pack",
                "BLUE",
                "--scope-label",
                "Live scope",
            ]
        )
        == 0
    )
    assert calls == [
        ("saved", saved, "Saved scope"),
        ("render", topology, "Saved scope", "default"),
        ("live", binary, "Live scope", None, config),
        ("render", topology, "Live scope", "BLUE"),
    ]
    assert capsys.readouterr().err.count("generated private lineage artifact") == 2


@pytest.mark.parametrize(
    ("selectors", "expected_profile"),
    [([], None), (["--profile", "named-org"], "named-org")],
)
def test_live_driver_supports_default_and_named_profile_credential_routes(
    tmp_path, monkeypatch, selectors, expected_profile
):
    monkeypatch.chdir(tmp_path)
    binary = tmp_path / "cja_auto_sdr"
    binary.write_text("binary", encoding="utf-8")
    binary.chmod(0o700)
    calls = []

    def fake_live(executable, *, scope_label, profile, config_file=None):
        calls.append((executable, scope_label, profile, config_file))
        return object()

    monkeypatch.setattr(driver, "acquire_live", fake_live)
    monkeypatch.setattr(driver, "render", lambda *_args, **_kwargs: "<html></html>")

    assert (
        driver.main(
            [
                "--live",
                "--binary",
                str(binary),
                *selectors,
                "--scope-label",
                "Live scope",
            ]
        )
        == 0
    )
    assert calls == [(binary, "Live scope", expected_profile, None)]


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--saved", "saved.json", "--live", "--scope-label", "Scope"],
        ["--saved", "saved.json"],
        ["--live", "--scope-label", "Scope"],
        ["--live", "--profile", "profile", "--scope-label", "Scope"],
        [
            "--live",
            "--binary",
            "/bin/tool",
            "--profile",
            "profile",
            "--config-file",
            "/tmp/config.json",
            "--scope-label",
            "Scope",
        ],
        ["--saved", "saved.json", "--scope-label", "Scope", "--profile", "profile"],
        ["--saved", "saved.json", "--scope-label", "Scope", "--color-pack", "blue"],
        ["--saved", "saved.json", "--scope-label", "Scope", "--unknown", CANARY],
        ["--saved", "saved.json", "--scope-label", f"Scope\n{CANARY}"],
    ],
)
def test_invalid_modes_and_hostile_arguments_fail_before_acquisition(
    tmp_path, monkeypatch, capsys, argv
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(driver, "acquire_saved", _unexpected)
    monkeypatch.setattr(driver, "acquire_live", _unexpected)

    with pytest.raises(SystemExit) as caught:
        driver.main(argv)

    assert caught.value.code == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "generate-cja-lineage-poc: invalid arguments\n"
    assert CANARY not in captured.err
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize("alias_kind", ["lexical", "symlink", "hardlink"])
def test_saved_destination_aliases_fail_before_source_read(tmp_path, monkeypatch, alias_kind):
    monkeypatch.chdir(tmp_path)
    output = tmp_path / driver.OUTPUT_FILENAME
    source = output if alias_kind == "lexical" else tmp_path / "saved.json"
    if alias_kind != "lexical":
        source.write_text("saved", encoding="utf-8")
        if alias_kind == "symlink":
            output.symlink_to(source)
        else:
            os.link(source, output)
    original = source.read_bytes() if source.exists() else b""
    monkeypatch.setattr(driver, "acquire_saved", _unexpected)

    assert driver.main(["--saved", str(source), "--scope-label", "Scope"]) == 3

    if source.exists():
        assert source.read_bytes() == original
    else:
        assert original == b""


@pytest.mark.parametrize("protected", ["binary", "config"])
def test_live_destination_identity_is_protected_before_acquisition(
    tmp_path, monkeypatch, protected
):
    monkeypatch.chdir(tmp_path)
    output = tmp_path / driver.OUTPUT_FILENAME
    binary = output if protected == "binary" else tmp_path / "cja_auto_sdr"
    config = output if protected == "config" else tmp_path / "config.json"
    if protected != "binary":
        binary.write_text("binary", encoding="utf-8")
        binary.chmod(0o700)
    if protected != "config":
        config.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(driver, "acquire_live", _unexpected)

    assert (
        driver.main(
            [
                "--live",
                "--binary",
                str(binary),
                "--config-file",
                str(config),
                "--scope-label",
                "Scope",
            ]
        )
        == 3
    )


def test_typed_acquisition_render_and_output_failures_are_content_free(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    saved = tmp_path / f"{CANARY}.json"
    saved.write_text("{}", encoding="utf-8")
    output = tmp_path / driver.OUTPUT_FILENAME
    output.write_bytes(b"prior-good")

    monkeypatch.setattr(
        driver,
        "acquire_saved",
        lambda *_args, **_kwargs: LineageDiscoveryFailure(LineageDiscoveryFailureCode.INVALID_JSON),
    )
    assert driver.main(["--saved", str(saved), "--scope-label", "Scope"]) == 3

    monkeypatch.setattr(driver, "acquire_saved", lambda *_args, **_kwargs: object())

    def fail_render(*_args, **_kwargs):
        raise LineageLayoutError(CANARY)

    monkeypatch.setattr(driver, "render", fail_render)
    assert driver.main(["--saved", str(saved), "--scope-label", "Scope"]) == 1

    monkeypatch.setattr(driver, "render", lambda *_args, **_kwargs: "html")
    monkeypatch.setattr(
        driver,
        "write_lineage_output",
        lambda *_args, **_kwargs: lineage_output.LineageOutputFailure(
            lineage_output.LineageOutputFailureCode.WRITE_FAILED
        ),
    )
    assert driver.main(["--saved", str(saved), "--scope-label", "Scope"]) == 1

    assert output.read_bytes() == b"prior-good"
    captured = capsys.readouterr()
    assert CANARY not in captured.err
    assert str(saved) not in captured.err
    assert captured.err.splitlines() == [
        "generate-cja-lineage-poc: input rejected",
        "generate-cja-lineage-poc: rendering failed",
        "generate-cja-lineage-poc: output failed",
    ]


def test_unexpected_acquisition_exception_is_redacted(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    saved = tmp_path / f"{CANARY}.json"
    saved.write_text("{}", encoding="utf-8")

    def fail_acquisition(*_args, **_kwargs):
        raise OSError(CANARY)

    monkeypatch.setattr(driver, "acquire_saved", fail_acquisition)

    assert driver.main(["--saved", str(saved), "--scope-label", "Scope"]) == 1
    assert capsys.readouterr().err == "generate-cja-lineage-poc: acquisition failed\n"


@pytest.mark.parametrize("operation", ["write", "chmod", "fsync", "replace"])
def test_atomic_writer_preserves_prior_artifact_and_removes_temp(tmp_path, monkeypatch, operation):
    destination = tmp_path / driver.OUTPUT_FILENAME
    destination.write_bytes(b"prior-good")
    destination.chmod(0o644)

    if operation == "write":
        monkeypatch.setattr(
            lineage_output.os, "write", lambda *_args: (_ for _ in ()).throw(OSError())
        )
    elif operation == "chmod":
        monkeypatch.setattr(
            lineage_output.os, "fchmod", lambda *_args: (_ for _ in ()).throw(OSError())
        )
    elif operation == "fsync":
        monkeypatch.setattr(
            lineage_output.os, "fsync", lambda *_args: (_ for _ in ()).throw(OSError())
        )
    else:
        monkeypatch.setattr(
            lineage_output.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError())
        )

    result = lineage_output.write_lineage_output(destination, "replacement")

    assert result == lineage_output.LineageOutputFailure(
        lineage_output.LineageOutputFailureCode.WRITE_FAILED
    )
    assert destination.read_bytes() == b"prior-good"
    assert list(tmp_path.glob(f".{driver.OUTPUT_FILENAME}.*.tmp")) == []


def test_atomic_writer_replaces_permissive_file_with_owner_only_mode(tmp_path):
    destination = tmp_path / driver.OUTPUT_FILENAME
    destination.write_bytes(b"old")
    destination.chmod(0o666)

    assert lineage_output.write_lineage_output(destination, "new") is None

    assert destination.read_bytes() == b"new"
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_atomic_writer_revalidates_destination_before_replace(tmp_path, monkeypatch):
    destination = tmp_path / driver.OUTPUT_FILENAME
    destination.write_bytes(b"prior-good")
    validations = 0

    def change_identity(_destination, _protected=()):
        nonlocal validations
        validations += 1
        if validations == 2:
            return lineage_output.LineageOutputFailure(
                lineage_output.LineageOutputFailureCode.UNSAFE_DESTINATION
            )
        return None

    monkeypatch.setattr(lineage_output, "validate_lineage_destination", change_identity)

    result = lineage_output.write_lineage_output(destination, "replacement")

    assert result == lineage_output.LineageOutputFailure(
        lineage_output.LineageOutputFailureCode.UNSAFE_DESTINATION
    )
    assert destination.read_bytes() == b"prior-good"
    assert list(tmp_path.glob(f".{driver.OUTPUT_FILENAME}.*.tmp")) == []


def test_output_error_values_and_encoding_failure(tmp_path, monkeypatch):
    failure = lineage_output.LineageOutputFailure(
        lineage_output.LineageOutputFailureCode.WRITE_FAILED
    )
    assert str(failure) == "write-failed"
    assert repr(failure) == "LineageOutputFailure(code='write-failed')"
    destination = tmp_path / "out.html"
    destination.write_text("prior")
    assert lineage_output.write_lineage_output(destination, "\ud800") == failure
    assert destination.read_text() == "prior"
    from pathlib import Path

    original = Path.lstat

    def fail(path, *a, **kw):
        if path == destination:
            raise PermissionError("private")
        return original(path, *a, **kw)

    monkeypatch.setattr(Path, "lstat", fail)
    assert (
        lineage_output.validate_lineage_destination(destination).code
        == lineage_output.LineageOutputFailureCode.UNSAFE_DESTINATION
    )


def test_output_protection_handles_consumed_identity_and_short_write(tmp_path, monkeypatch):
    destination = tmp_path / "out.html"
    outcomes = iter(
        [
            None,
            lineage_output.LineageOutputFailure(
                lineage_output.LineageOutputFailureCode.UNSAFE_DESTINATION
            ),
        ]
    )
    monkeypatch.setattr(lineage_output, "validate_lineage_destination", lambda *a: next(outcomes))
    assert (
        lineage_output.write_lineage_output(destination, "data").code
        == lineage_output.LineageOutputFailureCode.UNSAFE_DESTINATION
    )
    assert not destination.exists()
    monkeypatch.setattr(lineage_output.os, "write", lambda *a: 0)
    with pytest.raises(OSError):
        lineage_output._write_all(1, b"data")
