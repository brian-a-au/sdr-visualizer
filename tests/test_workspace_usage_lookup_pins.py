"""Pin which credential Workspace collection uses for each mix of sources.

These tests were written against 1.2.12, before ``--profile`` existed. They must
keep passing unchanged, because a new option may not change which credential a
run that works today uses.
"""

import json
from pathlib import Path

import pytest

from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.usage import collector
from sdr_visualizer.usage.auth import resolve_credentials

FIXTURES = json.loads(
    (Path(__file__).parent / "standard_cases" / "fixtures.json").read_text(encoding="utf-8")
)["credentials"]
A, B = FIXTURES["A"], FIXTURES["B"]
FIELDS = ("org_id", "client_id", "secret", "scopes")
PROFILE_VARIABLE = {"aa": "AA_PROFILE", "cja": "CJA_PROFILE"}
PROFILE_ROOT = {"aa": ".aa", "cja": ".cja"}


class _Spawned(Exception):
    pass


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """Give every test an empty home, an empty working folder and no credential variables."""
    home, work = tmp_path / "home", tmp_path / "work"
    home.mkdir()
    work.mkdir()
    for key in ("ORG_ID", "CLIENT_ID", "SECRET", "SCOPES", "SANDBOX", "AA_PROFILE", "CJA_PROFILE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(work)
    return home, work


def set_environment(monkeypatch, credential, omit=()):
    for field in FIELDS:
        if field not in omit:
            monkeypatch.setenv(field.upper(), credential[field])


def write_json(path, credential, omit=(), extra=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {key: value for key, value in credential.items() if key not in omit}
    path.write_text(json.dumps({**data, **(extra or {})}), encoding="utf-8")
    path.chmod(0o600)
    return path


def launch(monkeypatch, config_path=None, platform="cja", org=A["org_id"], credentials=None):
    """Return the request and the environment the parent hands to the worker."""
    seen = {}

    def popen(argv, **kwargs):
        seen["argv"], seen["env"] = argv, kwargs["env"]
        raise _Spawned

    request = {
        "platform": platform,
        "instance_id": "instance",
        "org_id": org,
        "company_id": "company" if platform == "aa" else None,
        "config_path": str(config_path) if config_path is not None else None,
        "scope": "all",
        "project_ids": None,
    }
    with monkeypatch.context() as patch, pytest.raises(_Spawned):
        patch.setattr(collector.subprocess, "Popen", popen)
        if credentials is None:
            collector._acquire(request)
        else:
            # Added with --profile: the parent hands a profile's values to the worker.
            collector._acquire(request, credentials)
    return request, seen["env"], seen["argv"]


def lookup(monkeypatch, config_path=None, platform="cja", org=A["org_id"]):
    """Resolve the credential as the worker does, from what the parent gave it."""
    request, environment, _ = launch(monkeypatch, config_path, platform, org)
    found = resolve_credentials(request["config_path"], expected_org=org, environ=environment)
    return {field: getattr(found, field) for field in FIELDS}


def test_complete_environment_is_used(monkeypatch):
    set_environment(monkeypatch, A)
    assert lookup(monkeypatch) == A


def test_config_file_beats_the_environment(monkeypatch, tmp_path):
    set_environment(monkeypatch, B)
    config = write_json(tmp_path / "config.json", A)
    assert lookup(monkeypatch, config) == A


def test_partial_config_file_does_not_take_fields_from_the_environment(monkeypatch, tmp_path):
    set_environment(monkeypatch, A)
    config = write_json(tmp_path / "config.json", A, omit=("secret",))
    with pytest.raises(InvalidSnapshotError, match="secret"):
        lookup(monkeypatch, config)


def test_config_file_with_sandbox_key_is_rejected(monkeypatch, tmp_path):
    config = write_json(tmp_path / "config.json", A, extra={"sandbox": "dev"})
    with pytest.raises(InvalidSnapshotError, match="Invalid Workspace authentication config"):
        lookup(monkeypatch, config)


@pytest.mark.parametrize("missing", FIELDS)
def test_partial_environment_is_an_error(monkeypatch, missing):
    set_environment(monkeypatch, A, omit=(missing,))
    with pytest.raises(InvalidSnapshotError, match=missing):
        lookup(monkeypatch)


def test_nothing_set_is_an_error(monkeypatch):
    with pytest.raises(InvalidSnapshotError):
        lookup(monkeypatch)


@pytest.mark.parametrize("platform", ["aa", "cja"])
def test_profile_variable_is_not_read(monkeypatch, isolated, platform):
    home, _ = isolated
    write_json(home / PROFILE_ROOT[platform] / "orgs" / "prod" / "config.json", A)
    monkeypatch.setenv(PROFILE_VARIABLE[platform], "prod")
    with pytest.raises(InvalidSnapshotError):
        lookup(monkeypatch, platform=platform)
    set_environment(monkeypatch, B)
    assert lookup(monkeypatch, platform=platform, org=B["org_id"]) == B


def test_dotenv_in_the_working_folder_is_not_read(monkeypatch, isolated):
    _, work = isolated
    lines = [f"{field.upper()}={A[field]}" for field in FIELDS]
    (work / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(InvalidSnapshotError):
        lookup(monkeypatch)
    set_environment(monkeypatch, B)
    assert lookup(monkeypatch, org=B["org_id"]) == B


def test_config_json_in_the_working_folder_is_not_read(monkeypatch, isolated):
    _, work = isolated
    write_json(work / "config.json", A)
    with pytest.raises(InvalidSnapshotError):
        lookup(monkeypatch)


def test_organization_must_match_the_asserted_one(monkeypatch):
    set_environment(monkeypatch, A)
    with pytest.raises(InvalidSnapshotError, match="organization mismatch"):
        lookup(monkeypatch, org=B["org_id"])


def test_worker_gets_only_the_allowed_variables_and_no_home(monkeypatch):
    set_environment(monkeypatch, A)
    monkeypatch.setenv("CJA_PROFILE", "prod")
    monkeypatch.setenv("SANDBOX", "dev")
    _, environment, argv = launch(monkeypatch)
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "ORG_ID", "CLIENT_ID", "SECRET", "SCOPES"}
    added = {"PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTHONIOENCODING"}
    assert set(environment) <= allowed | added
    assert "HOME" not in environment
    assert not any(A["secret"] in argument for argument in argv)
