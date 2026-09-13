"""One-source credential resolution and quiet, per-instance SDK authentication."""

from __future__ import annotations

import contextlib
import logging
import os
import stat
from dataclasses import dataclass

from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.usage.transport import TOKEN_URL, TransportError, decode_json


@dataclass(frozen=True, repr=False)
class Credentials:
    org_id: str
    client_id: str
    secret: str
    scopes: str

    def __repr__(self):
        return "Credentials(<redacted>)"


def resolve_credentials(config_path=None, *, expected_org, environ=None):
    """Read only the explicit source. Call inside the isolated API worker."""
    if config_path is not None:
        try:
            fd = os.open(config_path, os.O_RDONLY | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError
                raw = stream.read(65537)
            if len(raw) > 65536:
                raise ValueError
            source = decode_json(raw, max_depth=10, max_nodes=1000)
            if type(source) is not dict:
                raise ValueError
            # The SDK legacy technical-account field is ignored, never interpreted.
            allowed = {
                "org_id",
                "client_id",
                "secret",
                "scopes",
                "tech_id",
            }
            if set(source) - allowed:
                raise ValueError
        except (OSError, ValueError, TransportError):
            raise InvalidSnapshotError("Invalid Workspace authentication configuration") from None
    else:
        env = os.environ if environ is None else environ
        source = {key: env.get(key.upper()) for key in ("org_id", "client_id", "secret", "scopes")}
    values = {}
    for key in ("org_id", "client_id", "secret", "scopes"):
        value = source.get(key)
        if key == "scopes" and isinstance(value, list):
            if not value or any(type(v) is not str or not v.strip() for v in value):
                raise InvalidSnapshotError("Invalid Workspace authentication field: scopes")
            value = ",".join(value)
        if type(value) is not str or not value.strip():
            raise InvalidSnapshotError("Invalid Workspace authentication field: " + key)
        try:
            size = len(value.encode("utf-8"))
        except UnicodeError:
            size = 16385
        if size > 16384 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise InvalidSnapshotError("Invalid Workspace authentication field: " + key)
        if key == "scopes":
            scopes = value.split(",")
            if any(not scope.strip() for scope in scopes):
                raise InvalidSnapshotError("Invalid Workspace authentication field: scopes")
            value = ",".join(dict.fromkeys(scope.strip() for scope in scopes))
        values[key] = value
    # Four values capped at 16 KiB also cap the resolved quartet at 64 KiB.
    if values["org_id"] != expected_org:
        raise InvalidSnapshotError("Workspace authentication organization mismatch")
    return Credentials(**values)


@contextlib.contextmanager
def quiet_sdk():
    """Suppress process-local SDK diagnostics, including failed OAuth bodies."""
    previous = logging.root.manager.disable
    with open(os.devnull, "w") as sink:
        logging.disable(logging.CRITICAL)
        try:
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                yield
        finally:
            logging.disable(previous)


def initialize_sdk(platform, credentials, transport, company_id=None):
    """Initialize only under an already-installed guarded transport in the API child."""
    if not transport.active:
        raise RuntimeError("Transport guard is required before authentication")
    with quiet_sdk():
        try:
            if platform == "cja":
                from cjapy import CJA
                from cjapy.configs import ConfigObj

                config = ConfigObj(
                    org_id=credentials.org_id,
                    client_id=credentials.client_id,
                    secret=credentials.secret,
                    scopes=credentials.scopes,
                )
                return CJA(config_object=config)
            if platform == "aa" and company_id == transport.company_id:
                from aanalytics2 import Analytics
                from aanalytics2.configs import ConfigObj

                config = ConfigObj(
                    {
                        "org_id": credentials.org_id,
                        "client_id": credentials.client_id,
                        "secret": credentials.secret,
                        "scopes": credentials.scopes,
                        "tech_id": "",
                        "date_limit": 0,
                        "token": "",
                        "oauthTokenEndpointV2": TOKEN_URL,
                    },
                    {
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "Authorization": "Bearer ",
                        "x-api-key": credentials.client_id,
                        "x-proxy-global-company-id": company_id,
                    },
                )
                return Analytics(company_id=company_id, config=config, retry=0)
            raise InvalidSnapshotError("Invalid Workspace authentication platform context")
        except (TransportError, InvalidSnapshotError):
            raise
        except Exception:
            raise TransportError("Workspace authentication failed") from None
