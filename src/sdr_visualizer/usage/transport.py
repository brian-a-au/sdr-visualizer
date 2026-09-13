"""Process-local, bounded transport for the explicitly requested Adobe collection."""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote, unquote, urlsplit

TOKEN_URL = "https://ims-na1.adobelogin.com/ims/token/v3"


class TransportError(Exception):
    """Only fixed, non-sensitive diagnostic categories cross the worker boundary."""

    def __init__(
        self, limitation="Workspace request failed", *, failure="collection_error", status=None
    ):
        super().__init__(limitation)
        self.limitation, self.failure, self.status = limitation, failure, status


def decode_json(raw, *, max_depth=100, max_nodes=250000):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    def constant(_):
        raise ValueError

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        stack, nodes = [(value, 0)], 0
        while stack:
            item, depth = stack.pop()
            nodes += 1
            if depth > max_depth or nodes > max_nodes:
                raise ValueError
            if isinstance(item, str):
                item.encode("utf-8")
            elif isinstance(item, float) and not math.isfinite(item):
                raise ValueError
            elif isinstance(item, dict):
                stack.extend((key, depth + 1) for key in item)
                stack.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                stack.extend((child, depth + 1) for child in item)
        return value
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        raise TransportError("Response is not bounded valid JSON") from None


@dataclass(frozen=True)
class Receipt:
    status: int
    data: object
    received_at: str


class BoundedTransport:
    """Guard requests before SDK authentication; use only in the API subprocess."""

    def __init__(self, platform, company_id=None, deadline_seconds=180):
        self.platform, self.company_id = platform, company_id
        if platform not in ("aa", "cja") or (platform == "aa" and not company_id):
            raise ValueError("Invalid transport platform context")
        self.deadline = time.monotonic() + min(deadline_seconds, 180)
        self.request_attempts = self.transferred_bytes = 0
        self.active = False

    def route_url(self, kind, identifier=None):
        suffixes = {
            "projects": "/projects",
            "project": "/projects/",
            "dataview": "/data/dataviews/",
            "suite": "/reportsuites/collections/suites/",
        }
        if kind == "discovery" and self.platform == "aa":
            return "https://analytics.adobe.io/discovery/me"
        if kind not in suffixes:
            raise TransportError("Unsupported request route")
        base = (
            "https://cja.adobe.io"
            if self.platform == "cja"
            else "https://analytics.adobe.io/api/" + quote(self.company_id, safe="")
        )
        url = base + suffixes[kind]
        if kind != "projects":
            if not isinstance(identifier, str) or not identifier:
                raise TransportError("Missing request identifier")
            url += quote(identifier, safe="")
        self.validate_route("GET", url)
        return url

    def validate_route(self, method, url):
        if method == "POST" and url == TOKEN_URL:
            return
        parts = urlsplit(url)
        if (
            method != "GET"
            or parts.scheme != "https"
            or parts.query
            or parts.fragment
            or parts.username
            or parts.password
            or parts.port
        ):
            raise TransportError("Unsupported request route")
        segment = r"(?:[A-Za-z0-9_.~-]|%[0-9A-F]{2})+"
        if self.platform == "cja":
            pattern = rf"/(?:projects(?:/{segment})?|data/dataviews/{segment})"
            host = "cja.adobe.io"
        else:
            company = re.escape(quote(self.company_id, safe=""))
            pattern = rf"(?:/discovery/me|/api/{company}/(?:projects(?:/{segment})?|reportsuites/collections/suites/{segment}))"
            host = "analytics.adobe.io"
        if parts.netloc != host or not re.fullmatch(pattern, parts.path):
            raise TransportError("Unsupported request route")
        if any(part in (".", "..") for part in unquote(parts.path).replace("\\", "/").split("/")):
            raise TransportError("Unsupported request route")

    def __enter__(self):
        import requests

        if self.active:
            raise RuntimeError("Transport guard already active")
        self.original = requests.Session.request
        guard = self

        def guarded(session, method, url, **kwargs):
            return guard._request(session, method.upper(), url, **kwargs)

        requests.Session.request = guarded
        self.active = True
        return self

    def __exit__(self, *_):
        import requests

        requests.Session.request = self.original
        self.active = False

    def _request(self, session, method, url, **kwargs):
        from requests.adapters import HTTPAdapter

        self.validate_route(method, url)
        if (
            method == "GET"
            and self.platform == "aa"
            and "/api/" in url
            and kwargs.get("headers", {}).get("x-proxy-global-company-id") != self.company_id
        ):
            raise TransportError("Company request context mismatch")
        # Reset sessions built by SDKs (whose adapters otherwise enforce their own retries).
        session.trust_env = False
        session.adapters.clear()
        session.proxies = {}
        session.cert = None
        session.auth = None
        session.hooks = {"response": []}
        session.mount("https://", HTTPAdapter(max_retries=0))
        kwargs = {key: val for key, val in kwargs.items() if key in ("headers", "params", "data")}
        kwargs.update(timeout=(5, 15), verify=True, allow_redirects=False, stream=True)
        for attempt in range(2):
            if self.request_attempts >= 256 or time.monotonic() >= self.deadline:
                raise TransportError("Workspace request budget exhausted")
            self.request_attempts += 1
            response = None
            try:
                response = self.original(session, method, url, **kwargs)
                status = response.status_code
                if status in (401, 403, 404):
                    raise TransportError(
                        "Workspace resource inaccessible",
                        failure="permission_denied",
                        status=status,
                    )
                if 300 <= status < 400:
                    raise TransportError("Workspace redirects are forbidden", status=status)
                if status == 429 or 500 <= status <= 599:
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after is not None else 0.0
                    if (
                        method == "GET"
                        and attempt == 0
                        and 0 <= delay <= 5
                        and time.monotonic() + delay + 20 < self.deadline
                    ):
                        response.close()
                        time.sleep(delay)
                        continue
                    raise TransportError("Workspace retry budget exhausted", status=status)
                if not 200 <= status < 300:
                    raise TransportError("Workspace request failed", status=status)
                body = bytearray()
                for chunk in response.iter_content(chunk_size=65536):
                    self.transferred_bytes += len(chunk)
                    if (
                        len(body) + len(chunk) > 2 * 1024 * 1024
                        or self.transferred_bytes > 32 * 1024 * 1024
                        or time.monotonic() >= self.deadline
                    ):
                        raise TransportError("Workspace transfer budget exhausted")
                    body.extend(chunk)
                data = decode_json(bytes(body))
                if isinstance(data, dict) and any(k in data for k in ("error", "error_code")):
                    raise TransportError("Workspace response reported an error", status=status)
                response._content = bytes(body)
                response._content_consumed = True
                response.json = lambda data=data, **_: data
                response.workspace_received_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                return response
            except TransportError:
                raise
            except Exception:
                raise TransportError("Workspace transport failed") from None
            finally:
                if response is not None:
                    response.close()
        raise TransportError("Workspace retry budget exhausted")

    def get_json(self, url, headers=None, params=None):
        import requests

        if not self.active:
            raise RuntimeError("Transport guard is required")
        with requests.Session() as session:
            response = session.get(url, headers=headers or {}, params=params)
        return Receipt(response.status_code, response.json(), response.workspace_received_at)
