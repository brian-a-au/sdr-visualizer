"""The --profile option, the credential source line, and the read warning."""

import json
import os
import subprocess
from pathlib import Path

import pytest
from test_workspace_usage_cli import acquisition, command
from test_workspace_usage_collection import child, implementation, protocol
from test_workspace_usage_lookup_pins import A, B, launch, write_json

from sdr_visualizer.cli.main import main
from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.usage import collector, credential_source
from sdr_visualizer.usage.credential_source import (
    CredentialSourceError,
    mask_client_id,
    mask_secret,
    readable_by_others,
    select_source,
)

# The CLI helper asserts the organization "org", so the profiles here use it.
PROFILE = {**B, "org_id": "org"}
FOLDER = {"aa": ".aa", "cja": ".cja"}


@pytest.fixture
def home(monkeypatch, tmp_path):
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setenv("HOME", str(folder))
    monkeypatch.setenv("USERPROFILE", str(folder))
    return folder


def profile_file(home, platform="cja", name="prod"):
    return home / FOLDER[platform] / "orgs" / name / "config.json"


@pytest.fixture
def acquired(monkeypatch):
    calls = []

    def acquire(request, credentials=None):
        calls.append((request, credentials))
        return {**acquisition(), "client_id": mask_client_id(PROFILE["client_id"])}

    monkeypatch.setattr(collector, "_acquire", acquire)
    return calls


@pytest.mark.parametrize("platform", ["aa", "cja"])
def test_profile_is_read_by_the_main_process_and_named_in_the_output(
    tmp_path, home, acquired, capsys, platform
):
    path = write_json(profile_file(home, platform), PROFILE, extra={"sandbox": "dev"})
    assert main([*command(tmp_path, platform), "--profile", "prod"]) == 0
    request, credentials = acquired[0]
    assert request["config_path"] is None
    assert (credentials.client_id, credentials.secret) == (PROFILE["client_id"], PROFILE["secret"])
    assert PROFILE["secret"] not in json.dumps(request)
    err = capsys.readouterr().err
    assert (
        f"sdr-visualizer: Workspace credential source: profile prod ({path}), "
        "client ID bbbb****8888, secret ****\n"
    ) in err
    assert PROFILE["secret"] not in err and PROFILE["client_id"] not in err
    assert "warning" not in err and "notice" not in err


def test_quiet_hides_the_source_line_and_keeps_the_warning(tmp_path, home, acquired, capsys):
    path = write_json(profile_file(home), PROFILE)
    path.chmod(0o644)
    assert main([*command(tmp_path), "--profile", "prod", "--quiet"]) == 0
    err = capsys.readouterr().err
    assert "credential source" not in err
    assert err.count("can be read by the group or by other users") == 1
    assert f"sdr-visualizer: warning: credential file {path} can be read" in err


@pytest.mark.skipif(os.name == "nt", reason="mode bits do not describe access on Windows")
@pytest.mark.parametrize(
    "mode,through_symlink,warned",
    [(0o600, False, False), (0o640, False, True), (0o604, False, True), (0o644, True, True)],
)
def test_config_file_that_others_can_read_gives_one_warning(
    tmp_path, acquired, capsys, mode, through_symlink, warned
):
    config = write_json(tmp_path / "private" / "config.json", PROFILE)
    config.chmod(mode)
    if through_symlink:
        link = tmp_path / "private" / "link.json"
        link.symlink_to(config)
        config = link
    assert main([*command(tmp_path), "--workspace-usage-config", str(config)]) == 0
    request, credentials = acquired[0]
    assert request["config_path"] == str(config) and credentials is None
    err = capsys.readouterr().err
    assert err.count("can be read by the group or by other users") == int(warned)
    assert f"Workspace credential source: config file {config}, client ID bbbb****8888" in err


@pytest.mark.parametrize("platform", ["aa", "cja"])
def test_environment_source_is_named_and_the_profile_variable_gives_a_notice(
    tmp_path, home, acquired, capsys, monkeypatch, platform
):
    write_json(profile_file(home, platform, "other"), PROFILE)
    variable = {"aa": "AA_PROFILE", "cja": "CJA_PROFILE"}[platform]
    monkeypatch.setenv(variable, "other")
    assert main([*command(tmp_path, platform), "--quiet"]) == 0
    assert acquired[0][1] is None
    err = capsys.readouterr().err
    assert err.count(f"sdr-visualizer: notice: profile_variable_not_used: {variable} is set") == 1
    monkeypatch.delenv(variable)
    assert main(command(tmp_path, platform)) == 0
    err = capsys.readouterr().err
    assert "notice" not in err
    assert (
        "Workspace credential source: environment variables ORG_ID, CLIENT_ID, SECRET and "
        "SCOPES, client ID bbbb****8888, secret ****"
    ) in err


def test_failed_lookup_still_names_the_source(tmp_path, monkeypatch, capsys):
    def fail(request):
        raise InvalidSnapshotError("Workspace authentication or environment identity is invalid")

    monkeypatch.setattr(collector, "_acquire", fail)
    assert main(command(tmp_path)) == 3
    err = capsys.readouterr().err
    assert "Workspace credential source: environment variables ORG_ID, CLIENT_ID" in err
    assert "client ID" not in err
    assert main([*command(tmp_path), "--quiet"]) == 3
    assert "credential source" not in capsys.readouterr().err
    with pytest.raises(InvalidSnapshotError):
        collector.collect_workspace_usage(implementation(), organization_context="org")
    assert capsys.readouterr().err == ""


def test_library_collection_without_a_report_prints_nothing(tmp_path, home, acquired, capsys):
    from sdr_visualizer.usage import collect_workspace_usage

    write_json(profile_file(home), PROFILE)
    snapshot = json.loads(
        (Path(__file__).parent / "fixtures" / "cja_snapshot_clean.json").read_text("utf-8")
    )
    evidence = collect_workspace_usage(snapshot, organization_context="org", profile="prod")
    assert evidence["collection"]["source"]["kind"] == "sdk_candidates"
    assert acquired[0][1].org_id == "org"
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    "extra,message",
    [
        (["--profile", "../other"], "--profile is not valid"),
        (["--profile", ""], "--profile is not valid"),
        (["--profile", "a" * 65], "--profile is not valid"),
        (["--profile", "prod", "--workspace-usage-config", "c.json"], "cannot be used together"),
    ],
)
def test_bad_profile_options_exit_3_before_any_work(tmp_path, acquired, capsys, extra, message):
    with pytest.raises(SystemExit) as stopped:
        main([*command(tmp_path), *extra])
    assert stopped.value.code == 3
    assert message in capsys.readouterr().err
    assert acquired == []


def test_profile_needs_a_run_that_uses_a_credential(tmp_path, capsys):
    with pytest.raises(SystemExit) as stopped:
        main([command(tmp_path)[0], "--profile", "prod"])
    assert stopped.value.code == 3
    assert "--profile requires --dataview, --rsid or --collect-workspace-usage" in (
        capsys.readouterr().err
    )


@pytest.mark.parametrize(
    "content,code,missing",
    [
        (None, "profile_not_found", ()),
        ({**PROFILE, "scopes": ""}, "partial_source", ("scopes",)),
        ({"org_id": "org", "scopes": []}, "partial_source", ("client_id", "secret", "scopes")),
    ],
)
def test_profile_errors_have_codes_and_do_not_fall_back(
    tmp_path, home, acquired, capsys, monkeypatch, content, code, missing
):
    for key in ("org_id", "client_id", "secret", "scopes"):
        monkeypatch.setenv(key.upper(), PROFILE[key])
    if content is not None:
        write_json(profile_file(home), content)
    with pytest.raises(CredentialSourceError) as raised:
        select_source("cja", profile="prod", expected_org="org")
    assert (raised.value.code, raised.value.missing) == (code, missing)
    assert main([*command(tmp_path), "--profile", "prod"]) == 3
    assert acquired == []
    assert PROFILE["secret"] not in capsys.readouterr().err


def test_profile_keeps_the_strict_file_rules(home):
    write_json(profile_file(home), PROFILE, extra={"note": "x"})
    with pytest.raises(InvalidSnapshotError, match="Invalid Workspace authentication config"):
        select_source("cja", profile="prod", expected_org="org")
    write_json(profile_file(home), {**PROFILE, "scopes": ["openid", "AdobeID"]})
    source = select_source("cja", profile="prod", expected_org="org")
    assert source.credentials.scopes == "openid,AdobeID"
    assert PROFILE["secret"] not in repr(source)
    with pytest.raises(InvalidSnapshotError, match="organization mismatch"):
        select_source("cja", profile="prod", expected_org=A["org_id"])
    # An Analytics run does not read a CJA profile.
    with pytest.raises(CredentialSourceError) as raised:
        select_source("aa", profile="prod", expected_org="org")
    assert raised.value.code == "profile_not_found"


def test_library_rejects_a_profile_and_a_config_file_together(tmp_path):
    with pytest.raises(CredentialSourceError) as raised:
        select_source("cja", profile="prod", config_path=tmp_path / "c.json", expected_org="org")
    assert raised.value.code == "profile_and_config_both_given"
    with pytest.raises(CredentialSourceError) as raised:
        select_source("cja", profile="..", expected_org="org", home=tmp_path)
    assert raised.value.code == "invalid_profile_name"


def test_mode_checks_are_skipped_where_they_mean_nothing(tmp_path, monkeypatch):
    path = write_json(tmp_path / "config.json", PROFILE)
    path.chmod(0o644)
    assert readable_by_others(path)
    assert not readable_by_others(tmp_path / "missing.json")
    monkeypatch.setattr(credential_source.os, "name", "nt")
    try:
        assert not readable_by_others(path)
    finally:
        monkeypatch.undo()
    assert mask_secret("") == "" and mask_secret("abc") == "****"


@pytest.mark.parametrize("masked", ["aaaa****4444", "****"])
def test_worker_reports_only_a_masked_client_id(masked):
    result = protocol([{"kind": "credential", "client_id": masked}])
    assert result["client_id"] == masked


@pytest.mark.parametrize(
    "messages",
    [
        [{"kind": "credential", "client_id": "aaaa1111bbbb2222cccc3333dddd4444"}],
        [{"kind": "credential", "client_id": 7}],
        [{"kind": "credential", "client_id": "\u001b[2J****\u001b[2J"}],
        [{"kind": "credential", "client_id": "aaaa****444\u007f"}],
        [{"kind": "credential", "client_id": "aaaa*****4444"}],
        [{"kind": "credential", "client_id": "aaaa****4444", "secret": "x"}],
        [{"kind": "credential", "client_id": "****"}, {"kind": "credential", "client_id": "****"}],
    ],
)
def test_parent_rejects_an_unmasked_or_repeated_client_id(messages):
    result = protocol(messages)
    assert result["retrieval"]["status"] == "failed"
    assert result["client_id"] in (None, "****")
    assert "aaaa1111" not in json.dumps(result)


def test_worker_started_for_a_profile_gets_only_the_allowed_variables(home, monkeypatch):
    write_json(profile_file(home), PROFILE)
    monkeypatch.setenv("CJA_PROFILE", "prod")
    monkeypatch.setenv("ORG_ID", A["org_id"])
    monkeypatch.setenv("SECRET", A["secret"])
    source = select_source("cja", profile="prod", expected_org="org")
    request, environment, argv = launch(monkeypatch, org="org", credentials=source.credentials)
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "ORG_ID", "CLIENT_ID", "SECRET", "SCOPES"}
    added = {"PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTHONIOENCODING"}
    assert set(environment) <= allowed | added
    assert "HOME" not in environment and "USERPROFILE" not in environment
    # All four values come from the profile. None stays from the environment.
    assert [environment[key] for key in ("ORG_ID", "CLIENT_ID", "SECRET", "SCOPES")] == [
        PROFILE[key] for key in ("org_id", "client_id", "secret", "scopes")
    ]
    sent = json.dumps(request) + " ".join(argv)
    assert PROFILE["secret"] not in sent and PROFILE["client_id"] not in sent


def test_real_worker_code_emits_the_masked_client_id(monkeypatch):
    messages = child(monkeypatch)
    assert messages[0] == {"kind": "credential", "client_id": "synt****t-id"}


@pytest.mark.parametrize("mode,tool", [("--dataview", "cja_auto_sdr"), ("--rsid", "aa_auto_sdr")])
def test_profile_is_passed_to_the_generator_child(monkeypatch, capsys, mode, tool):
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr("sdr_visualizer.input.shell_out.shutil.which", lambda name: "/bin/" + name)
    monkeypatch.setattr("sdr_visualizer.input.shell_out.subprocess.run", fake_run)
    assert main([mode, "instance", "--profile", "client-a.eu_west"]) == 3
    assert commands[0][:2] == [f"/bin/{tool}", "instance"]
    assert commands[0][-2:] == ["--profile", "client-a.eu_west"]
    assert f"sdr-visualizer: {tool} credential source: profile client-a.eu_west" in (
        capsys.readouterr().err
    )
    assert main([mode, "instance"]) == 3
    assert "--profile" not in commands[1]
    assert "credential source" not in capsys.readouterr().err
