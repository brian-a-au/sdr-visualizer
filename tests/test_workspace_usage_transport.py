import pytest

from sdr_visualizer.usage.transport import BoundedTransport, TransportError


def test_routes_reject_other_hosts():
    transport = BoundedTransport("cja")
    with pytest.raises(TransportError):
        transport.validate_route("GET", "https://evil.invalid/data/projects")
    assert transport.request_attempts == 0


def test_routes_encode_identifiers():
    assert BoundedTransport("cja").route_url("project", "a/b") == (
        "https://cja.adobe.io/projects/a%2Fb"
    )


class FakeResponse:
    def __init__(self, body=b'{"ok":true}', status=200, headers=None):
        self.status_code, self.headers = status, headers or {}
        self.body, self.closed = body, False

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset : offset + chunk_size]

    def close(self):
        self.closed = True


@pytest.mark.parametrize("status", [401, 403, 404, 302, 400])
def test_status_precedes_bad_json(monkeypatch, status):
    import requests

    monkeypatch.setattr(
        requests.Session, "request", lambda *a, **kw: FakeResponse(b"secret body", status)
    )
    with BoundedTransport("cja") as transport:
        with pytest.raises(TransportError) as error:
            transport.get_json(transport.route_url("projects"))
        assert error.value.status == status
        assert "secret" not in str(error.value)
        assert transport.request_attempts == 1


def test_retries_and_forced_request_options(monkeypatch):
    import requests

    calls = []

    def fake(session, method, url, **kw):
        calls.append(kw)
        assert session.trust_env is False
        assert session.adapters["https://"].max_retries.total == 0
        return FakeResponse(status=503 if len(calls) == 1 else 200)

    monkeypatch.setattr(requests.Session, "request", fake)
    with BoundedTransport("cja") as transport:
        result = transport.get_json(transport.route_url("projects"))
        assert result.data == {"ok": True}
        assert result.received_at.endswith("Z")
        assert transport.request_attempts == 2
    assert calls[0]["timeout"] == (5, 15)
    assert calls[0]["verify"] is True
    assert calls[0]["allow_redirects"] is False
    assert calls[0]["stream"] is True


@pytest.mark.parametrize(
    "body",
    [b'{"a":1,"a":2}', b"NaN", b'"\\ud800"', b"\xff", b"{}" * 1100000, b'{"error":"secret"}'],
)
def test_response_bounds(monkeypatch, body):
    import requests

    monkeypatch.setattr(requests.Session, "request", lambda *a, **kw: FakeResponse(body))
    with BoundedTransport("cja") as transport, pytest.raises(TransportError):
        transport.get_json(transport.route_url("projects"))


def test_request_exception_count_and_guard_restoration(monkeypatch):
    import requests

    def fake(*a, **kw):
        raise RuntimeError("secret")

    monkeypatch.setattr(requests.Session, "request", fake)
    with BoundedTransport("cja") as transport:
        with pytest.raises(TransportError, match="transport failed"):
            transport.get_json(transport.route_url("projects"))
        assert transport.request_attempts == 1
    assert requests.Session.request is fake


def test_attempt_limit(monkeypatch):
    import requests

    monkeypatch.setattr(requests.Session, "request", lambda *a, **kw: pytest.fail("sent"))
    with BoundedTransport("cja") as transport:
        transport.request_attempts = 256
        with pytest.raises(TransportError, match="budget"):
            transport.get_json(transport.route_url("projects"))


@pytest.mark.parametrize(
    "url",
    [
        "https://cja.adobe.io/projects/%2E%2E",
        "https://cja.adobe.io/projects/..",
        "https://cja.adobe.io/projects?a=1",
        "https://cja.adobe.io:443/projects",
        "http://cja.adobe.io/projects",
        "https://evil@cja.adobe.io/projects",
        "https://cja.adobe.io/projects#x",
    ],
)
def test_forbidden_routes(url):
    with pytest.raises(TransportError):
        BoundedTransport("cja").validate_route("GET", url)


@pytest.mark.parametrize("status,delay", [(429, "6"), (500, "-1"), (503, "NaN"), (502, "bad")])
def test_retry_limits(monkeypatch, status, delay):
    import requests

    monkeypatch.setattr(
        requests.Session,
        "request",
        lambda *a, **kw: FakeResponse(status=status, headers={"Retry-After": delay}),
    )
    with BoundedTransport("cja") as transport:
        with pytest.raises(TransportError):
            transport.get_json(transport.route_url("projects"))
        assert transport.request_attempts == 1


def test_json_structure_bounds():
    from sdr_visualizer.usage.transport import decode_json

    for body, kwargs in [
        (b"[[[]]]", {"max_depth": 1}),
        (b"[1,2,3]", {"max_nodes": 2}),
        (b"1e999", {}),
    ]:
        with pytest.raises(TransportError):
            decode_json(body, **kwargs)


def test_aa_routes_and_company_header(monkeypatch):
    import requests

    monkeypatch.setattr(requests.Session, "request", lambda *a, **kw: FakeResponse())
    with BoundedTransport("aa", "company") as transport:
        assert transport.route_url("discovery") == "https://analytics.adobe.io/discovery/me"
        url = transport.route_url("suite", "virtual")
        with pytest.raises(TransportError, match="Company"):
            transport.get_json(url)
        assert transport.get_json(url, {"x-proxy-global-company-id": "company"}).status == 200


def test_total_transfer_limit(monkeypatch):
    import requests

    monkeypatch.setattr(requests.Session, "request", lambda *a, **kw: FakeResponse())
    with BoundedTransport("cja") as transport:
        transport.transferred_bytes = 32 * 1024 * 1024
        with pytest.raises(TransportError, match="transfer budget"):
            transport.get_json(transport.route_url("projects"))


def test_invalid_context_and_inactive_guard():
    with pytest.raises(ValueError):
        BoundedTransport("bad")
    with pytest.raises(ValueError):
        BoundedTransport("aa")
    transport = BoundedTransport("cja")
    with pytest.raises(TransportError):
        transport.route_url("bad")
    with pytest.raises(TransportError):
        transport.route_url("project")
    with pytest.raises(RuntimeError):
        transport.get_json(transport.route_url("projects"))
    with transport, pytest.raises(RuntimeError):
        transport.__enter__()


def test_oauth_never_retries(monkeypatch):
    import requests

    from sdr_visualizer.usage.transport import TOKEN_URL

    monkeypatch.setattr(requests.Session, "request", lambda *a, **kw: FakeResponse(status=503))
    with BoundedTransport("cja") as transport:
        with pytest.raises(TransportError):
            requests.post(TOKEN_URL)
        assert transport.request_attempts == 1


def test_expired_budget_stops_before_send(monkeypatch):
    import requests

    monkeypatch.setattr(requests.Session, "request", lambda *a, **kw: pytest.fail("sent"))
    with BoundedTransport("cja", deadline_seconds=-1) as transport:
        with pytest.raises(TransportError):
            transport.get_json(transport.route_url("projects"))
        assert transport.request_attempts == 0


@pytest.mark.parametrize("identifier", ["../projects", "a/../../projects", "a\\..\\projects"])
def test_encoded_traversal_is_rejected(identifier):
    with pytest.raises(TransportError):
        BoundedTransport("cja").route_url("project", identifier)
