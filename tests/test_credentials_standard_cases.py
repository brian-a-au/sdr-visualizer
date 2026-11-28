"""Run the shared cases of the Adobe credentials standard against this tool.

This module is the tool's adapter. It builds each case in a temporary home and
working folder, runs the Workspace credential lookup, and checks ``expect``.
The tool serves both products, so each case runs once for ``aa`` and once for
``cja``. Every case listed in ``known-differences.json`` must fail, and every
other case that applies must pass.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest
from test_workspace_usage_lookup_pins import FIELDS, PROFILE_ROOT, PROFILE_VARIABLE, launch

from sdr_visualizer.cli.main import main
from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.usage.auth import resolve_credentials
from sdr_visualizer.usage.credential_source import (
    CredentialSourceError,
    mask_client_id,
    mask_secret,
    select_source,
    valid_profile_name,
)

REPO = Path(__file__).resolve().parent.parent
CASES_FOLDER = Path(__file__).parent / "standard_cases"
TOOL = "sdr-visualizer"
PRODUCTS = ("aa", "cja")
CREDENTIALS = json.loads((CASES_FOLDER / "fixtures.json").read_text(encoding="utf-8"))[
    "credentials"
]
KNOWN = json.loads((REPO / "known-differences.json").read_text(encoding="utf-8"))
EXPECTED_TO_FAIL = {case for entry in KNOWN["differences"] for case in entry.get("cases", [])}
SOURCE_NAMES = {"config": "flag_config", "profile": "flag_profile", "environment": "environment"}
# A config_check case runs through the lookup only when it reads a profile and
# asks for nothing that needs the command's own output.
LOOKUP_EXPECTATIONS = {"source", "error", "warning", "warning_count", "ok", "profile_folder"}


def _load_cases():
    cases = []
    for path in sorted(CASES_FOLDER.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        cases.extend(data.get("cases", []) if isinstance(data, dict) else [])
    return cases


CASES = _load_cases()


def skip_reason(case, product):
    """Return why a case does not apply to this tool, or None when it runs."""
    given = case["given"]
    if "products" in case and product not in case["products"]:
        return "the case is for the other product"
    if "tools" in case and TOOL not in case["tools"]:
        return "the case is for another tool"
    if given.get("action") == "create_profile":
        return "the tool writes no profile"
    command = given.get("command")
    if command == "live_test":
        return "the tool has no live test command"
    if command == "config_check" and (
        set(given["sources"]) != {"flag_profile"} or not set(case["expect"]) <= LOOKUP_EXPECTATIONS
    ):
        return "the tool has no config check command"
    if case["rule"] == "L1.3" and os.name == "nt":
        return "mode bits do not describe access on Windows"
    return None


@pytest.fixture
def folders(monkeypatch, tmp_path):
    home, work = tmp_path / "home", tmp_path / "parent" / "work"
    home.mkdir()
    work.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(work)
    return home, work


def _values(spec):
    values = dict(CREDENTIALS[spec["credential"]])
    for key in spec.get("omit", ()):
        del values[key]
    values.update(spec.get("override", {}))
    return values


def _write_json(path, spec):
    path.parent.mkdir(parents=True, exist_ok=True)
    target = path
    if spec.get("through_symlink"):
        target = path.with_name("target-" + path.name)
        path.symlink_to(target)
    target.write_text(json.dumps({**_values(spec), **spec.get("extra_keys", {})}), encoding="utf-8")
    target.chmod(int(spec.get("file_mode", "0600"), 8))


def _profile_file(home, product, name):
    return home / PROFILE_ROOT[product] / "orgs" / name / "config.json"


def build(case, product, monkeypatch, home, work):
    """Create every source the case names. Return the options a person would pass."""
    options = {"config_path": None, "profile": None}
    for name, spec in case["given"].get("sources", {}).items():
        if name == "flag_profile":
            options["profile"] = spec["name"]
            if "credential" in spec:
                _write_json(_profile_file(home, product, spec["name"]), spec)
        elif name == "flag_config":
            options["config_path"] = work.parent / "given-config.json"
            _write_json(options["config_path"], spec)
        elif name in ("profile_variable", "profile_variable_target"):
            _write_json(_profile_file(home, product, spec["name"]), spec)
            if name == "profile_variable":
                monkeypatch.setenv(PROFILE_VARIABLE[product], spec["name"])
        elif name == "environment":
            if spec.get("other_settings"):
                monkeypatch.setenv("SDR_VISUALIZER_UNRELATED_SETTING", "1")
            if "credential" in spec:
                for key, value in _values(spec).items():
                    monkeypatch.setenv(key.upper(), value)
        elif name == "dotenv":
            folder = work.parent if spec.get("location") == "parent_folder" else work
            lines = [f"{key.upper()}={value}" for key, value in _values(spec).items()]
            for key, value in spec.get("extra_keys", {}).items():
                key = PROFILE_VARIABLE[product] if key == "PROFILE_VARIABLE" else key
                lines.append(f"{key}={value}")
            (folder / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
        elif name == "default_config":
            # The tool has no default config file. The generators use config.json
            # in the working folder, so the case puts one there.
            _write_json(work / "config.json", spec)
        else:
            raise RuntimeError(f"the adapter does not know the source {name}")
    return options


def expected_org(case):
    """Return the organization the person asserts with --workspace-usage-org."""
    name = case["expect"].get("credential")
    if name is None:
        specs = [s for s in case["given"].get("sources", {}).values() if "credential" in s]
        name = specs[0]["credential"] if specs else "A"
    return CREDENTIALS[name]["org_id"]


def run_lookup(case, product, monkeypatch, home, work):
    """Run the parent's source choice and the worker's read, with no real worker."""
    options = build(case, product, monkeypatch, home, work)
    org = expected_org(case)
    try:
        source = select_source(product, expected_org=org, **options)
        request, environment, _ = launch(
            monkeypatch, options["config_path"], product, org, credentials=source.credentials
        )
        found = resolve_credentials(request["config_path"], expected_org=org, environ=environment)
    except CredentialSourceError as error:
        return {"error": error.code, "missing": list(error.missing)}
    except InvalidSnapshotError:
        return {"error": "unnamed", "missing": []}
    return {
        "error": None,
        "source": SOURCE_NAMES[source.kind],
        "credential": {field: getattr(found, field) for field in FIELDS},
        "warnings": [code for code, _ in source.warnings],
        "folder": source.path.parent if source.path is not None else None,
    }


def check_lookup(case, product, monkeypatch, home, work):
    result = run_lookup(case, product, monkeypatch, home, work)
    for key, expected in case["expect"].items():
        if key == "error":
            assert result["error"] == expected
        elif key == "missing":
            assert result["missing"] == expected
        elif key == "source":
            assert result["error"] is None and result["source"] == expected
        elif key == "credential":
            assert result["error"] is None and result["credential"] == CREDENTIALS[expected]
        elif key == "ok":
            assert (result["error"] is None) is expected
        elif key == "warning":
            assert expected in result["warnings"]
        elif key == "warning_count":
            assert len(result["warnings"]) == expected
        elif key == "profile_folder":
            assert result["folder"] == home / expected.removeprefix("~/")
        else:
            raise RuntimeError(f"the adapter does not know the expectation {key}")


def _holds_secret(arguments, secret):
    windows = {secret[index : index + 8] for index in range(len(secret) - 7)}
    return any(window in str(argument) for argument in arguments for window in windows)


def check_children(case, product, monkeypatch, home, work):
    """Check the arguments of the API worker and of the generator child."""
    assert case["expect"] == {"child_arguments_exclude_secret": True}
    build(case, product, monkeypatch, home, work)
    credential = CREDENTIALS[case["given"]["sources"]["environment"]["credential"]]
    secret, org = credential["secret"], credential["org_id"]

    # The worker with the environment as the source.
    _, environment, argv = launch(monkeypatch, None, product, org)
    assert environment["SECRET"] == secret
    assert not _holds_secret(argv, secret)

    # The worker with a profile as the source.
    _write_json(_profile_file(home, product, "prod"), {"credential": "B"})
    source = select_source(product, profile="prod", expected_org=CREDENTIALS["B"]["org_id"])
    _, environment, argv = launch(
        monkeypatch, None, product, CREDENTIALS["B"]["org_id"], credentials=source.credentials
    )
    assert environment["SECRET"] == CREDENTIALS["B"]["secret"]
    assert not _holds_secret(argv, CREDENTIALS["B"]["secret"])
    assert not _holds_secret(argv, secret)

    # The generator child, with and without a profile.
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr("sdr_visualizer.input.shell_out.shutil.which", lambda name: "/bin/" + name)
    monkeypatch.setattr("sdr_visualizer.input.shell_out.subprocess.run", fake_run)
    mode = "--rsid" if product == "aa" else "--dataview"
    assert main([mode, "instance", "--quiet"]) == 3
    assert main([mode, "instance", "--profile", "prod", "--quiet"]) == 3
    assert len(commands) == 2
    assert "--profile" not in commands[0]
    assert commands[1][-2:] == ["--profile", "prod"]
    for command in commands:
        assert not _holds_secret(command, secret)
        assert not _holds_secret(command, CREDENTIALS["B"]["secret"])


def check(case, product, monkeypatch, home, work):
    given, expect = case["given"], case["expect"]
    if "client_id" in given:
        assert mask_client_id(given["client_id"]) == expect["masked"]
    elif "secret" in given:
        assert mask_secret(given["secret"]) == expect["masked"]
    elif "profile_name" in given:
        assert valid_profile_name(given["profile_name"]) is expect["valid"]
    elif given.get("command") == "run_child":
        check_children(case, product, monkeypatch, home, work)
    else:
        check_lookup(case, product, monkeypatch, home, work)


@pytest.mark.parametrize("product", PRODUCTS)
@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_shared_case(case, product, monkeypatch, folders):
    reason = skip_reason(case, product)
    if reason is not None:
        pytest.skip(reason)
    if case["id"] in EXPECTED_TO_FAIL:
        # A listed case that starts to pass fails here, so the list can only get shorter.
        with pytest.raises(AssertionError):
            check(case, product, monkeypatch, *folders)
    else:
        check(case, product, monkeypatch, *folders)


def test_every_listed_case_exists_and_runs():
    by_id = {case["id"]: case for case in CASES}
    assert len(by_id) == len(CASES)
    for case_id in EXPECTED_TO_FAIL:
        assert case_id in by_id
        assert all(skip_reason(by_id[case_id], product) is None for product in PRODUCTS)


def test_the_cases_the_tool_runs():
    """Pin which cases apply, so a change to the skip rules is seen in review."""
    ran = sorted(
        case["id"] for case in CASES if any(skip_reason(case, p) is None for p in PRODUCTS)
    )
    lookup = [f"lookup-{n:03d}" for n in range(1, 12)]
    partial = [f"partial-{n:03d}" for n in range(1, 7)]
    names = [f"name-{n:03d}" for n in range(1, 14)]
    masks = [f"mask-{n:03d}" for n in (1, 2, 3, 4, 5, 6, 9)]
    assert ran == sorted(
        ["check-009", "check-010", "check-011", "perm-004", *lookup, *partial, *names, *masks]
    )


def test_known_differences_file_has_the_shared_shape():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(
        (CASES_FOLDER / "known-differences-v1.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(KNOWN, schema)
    assert KNOWN["tool"] == TOOL


def test_copied_cases_match_their_recorded_checksums():
    import hashlib

    record = json.loads((CASES_FOLDER / "SOURCE.json").read_text(encoding="utf-8"))
    for name, digest in record["files"].items():
        assert hashlib.sha256((CASES_FOLDER / name).read_bytes()).hexdigest() == digest
    present = {path.name for path in CASES_FOLDER.glob("*.json")} - {"SOURCE.json"}
    assert present == set(record["files"])
