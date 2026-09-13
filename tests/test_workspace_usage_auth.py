import pytest

from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.usage.auth import resolve_credentials


def test_environment_credentials_and_redaction():
    creds = resolve_credentials(
        expected_org="org",
        environ={"ORG_ID": "org", "CLIENT_ID": "client", "SECRET": "sensitive", "SCOPES": "a, b"},
    )
    assert creds.scopes == "a,b"
    assert "sensitive" not in repr(creds)


def test_config_never_merges(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"org_id":"org"}')
    with pytest.raises(InvalidSnapshotError, match="client_id"):
        resolve_credentials(path, expected_org="org", environ={"CLIENT_ID": "other"})


@pytest.mark.parametrize("platform", ["aa", "cja"])
def test_actual_sdk_authentication_uses_guard(monkeypatch, platform):
    import requests
    from test_workspace_usage_transport import FakeResponse

    from sdr_visualizer.usage.auth import initialize_sdk
    from sdr_visualizer.usage.transport import TOKEN_URL, BoundedTransport

    calls = []

    def fake(session, method, url, **kwargs):
        calls.append((method, url))
        assert kwargs["timeout"] == (5, 15)
        assert kwargs["allow_redirects"] is False
        return FakeResponse(b'{"access_token":"synthetic-token","expires_in":3600}')

    monkeypatch.setattr(requests.Session, "request", fake)
    creds = resolve_credentials(
        expected_org="org",
        environ={"ORG_ID": "org", "CLIENT_ID": "client", "SECRET": "sensitive", "SCOPES": "a"},
    )
    with BoundedTransport(platform, company_id="company" if platform == "aa" else None) as guard:
        client = initialize_sdk(platform, creds, guard, "company" if platform == "aa" else None)
        assert client is not None
        assert guard.request_attempts == 1
    assert calls == [("POST", TOKEN_URL)]


@pytest.mark.parametrize(
    "raw",
    [
        '{"org_id":"a","org_id":"a"}',
        "NaN",
        "[]",
        '{"endpoint":"https://evil.invalid"}',
        '"\\ud800"',
    ],
)
def test_bad_configs_are_redacted(tmp_path, raw):
    path = tmp_path / "secret-path.json"
    path.write_text(raw)
    with pytest.raises(InvalidSnapshotError) as error:
        resolve_credentials(path, expected_org="org")
    assert str(path) not in str(error.value)
    assert raw not in str(error.value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("org_id", None),
        ("client_id", 1),
        ("secret", ""),
        ("secret", "\ud800"),
        ("secret", "a" * 16385),
        ("secret", "a\nb"),
        ("scopes", []),
        ("scopes", [1]),
        ("scopes", "a,,b"),
        ("scopes", [""]),
    ],
)
def test_invalid_fields(field, value):
    env = {"ORG_ID": "org", "CLIENT_ID": "client", "SECRET": "secret", "SCOPES": "a"}
    env[field.upper()] = value
    with pytest.raises(InvalidSnapshotError, match=field):
        resolve_credentials(expected_org="org", environ=env)


def test_config_wins_and_legacy_field_ignored(tmp_path):
    import json

    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            dict(
                org_id="org",
                client_id="client",
                secret="secret",
                scopes=["a", "b", "a"],
                tech_id="ignored",
            )
        )
    )
    result = resolve_credentials(path, expected_org="org", environ={"ORG_ID": "wrong"})
    assert result.scopes == "a,b"
    with pytest.raises(InvalidSnapshotError, match="organization mismatch"):
        resolve_credentials(path, expected_org="other")


@pytest.mark.parametrize("kind", ["large", "directory", "missing"])
def test_bad_config_files(tmp_path, kind):
    path = tmp_path / kind
    if kind == "large":
        path.write_bytes(b" " * 65537)
    elif kind == "directory":
        path.mkdir()
    with pytest.raises(InvalidSnapshotError):
        resolve_credentials(path, expected_org="org")


def test_special_file_rejected():
    with pytest.raises(InvalidSnapshotError):
        resolve_credentials("/dev/null", expected_org="org")


@pytest.mark.parametrize("body,status", [(b'{"error":"private"}', 401), (b"{}", 200)])
def test_sdk_auth_failure_is_sanitized(monkeypatch, body, status):
    import requests
    from test_workspace_usage_transport import FakeResponse

    from sdr_visualizer.usage.auth import Credentials, initialize_sdk
    from sdr_visualizer.usage.transport import BoundedTransport, TransportError

    monkeypatch.setattr(requests.Session, "request", lambda *a, **kw: FakeResponse(body, status))
    credentials = Credentials("org", "id", "secret", "scope")
    with BoundedTransport("cja") as transport:
        with pytest.raises(TransportError) as error:
            initialize_sdk("cja", credentials, transport)
        assert "private" not in str(error.value)
        assert error.value.failure == ("permission_denied" if status == 401 else "collection_error")
        assert transport.request_attempts == 1
        with pytest.raises(InvalidSnapshotError):
            initialize_sdk("wrong", credentials, transport)
    with pytest.raises(RuntimeError):
        initialize_sdk("cja", credentials, transport)


def test_quiet_sdk_suppresses_output_and_restores_logging(capsys):
    import logging

    from sdr_visualizer.usage.auth import quiet_sdk

    before = logging.root.manager.disable
    with pytest.raises(ValueError), quiet_sdk():
        print("secret")
        logging.error("secret")
        raise ValueError
    assert "secret" not in capsys.readouterr().out
    assert logging.root.manager.disable == before
