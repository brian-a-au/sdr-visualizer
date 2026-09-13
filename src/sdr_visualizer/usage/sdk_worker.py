"""Isolated, credential-free and network-denied upstream SDK matching."""

from __future__ import annotations

import contextlib
import importlib
import json
import logging
import os
import selectors
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.usage.normalize import (
    EXCLUDED_PROJECTS_LIMITATION,
    MAX_IPC_BYTES,
    MatchResult,
    bounded_json,
    candidate_record,
    normalize_findings,
    sanitize_projects,
    validate_components,
)


class NetworkDenied(RuntimeError):
    """Matching may never acquire definitions or authenticate."""


class DenyNetwork:
    def __call__(self, *args, **kwargs):
        raise NetworkDenied("SDK automatic fetching is unsupported")

    def __getattr__(self, name):
        return self


def _run_matching(request, emit):
    """Child-only: no SDK imports or mutable network guards in the caller process."""
    for key in ("ORG_ID", "CLIENT_ID", "SECRET", "SCOPES"):
        os.environ.pop(key, None)
    deny = DenyNetwork()
    import requests

    class DeniedSocket(socket.socket):
        connect = connect_ex = deny

    socket.socket = DeniedSocket
    socket.create_connection = deny
    requests.sessions.Session.request = deny
    adapter = importlib.import_module(f"sdr_visualizer.usage.{request['platform']}_sdk")
    client, parsed, excluded = adapter.prepare(request["projects"], deny)
    if excluded:
        emit(
            {
                "kind": "limitation",
                "value": EXCLUDED_PROJECTS_LIMITATION,
            }
        )
    metadata = {project["id"]: project for project in request["projects"]}
    for component in request["components"]:
        emit({"kind": "started", "component": component})
        try:
            projects = (
                normalize_findings(adapter.find(client, parsed, component), component, metadata)
                if parsed
                else []
            )
            record = candidate_record(component, request["checked_at"], projects)
        except Exception as error:
            failure = "unsupported" if isinstance(error, NetworkDenied) else "collection_error"
            emit(
                {
                    "kind": "result",
                    "value": candidate_record(component, request["checked_at"], [], failure),
                }
            )
            return
        emit({"kind": "result", "value": record})
    emit({"kind": "done"})


def _child():
    protocol = sys.stdout.buffer
    size = 0

    def emit(value):
        nonlocal size
        data = bounded_json(value) + b"\n"
        size += len(data)
        if size > MAX_IPC_BYTES:
            raise ValueError("SDK output budget exceeded")
        protocol.write(data)
        protocol.flush()

    logging.disable(logging.CRITICAL)
    with (
        open(os.devnull, "w") as sink,
        contextlib.redirect_stdout(sink),
        contextlib.redirect_stderr(sink),
    ):
        try:
            data = sys.stdin.buffer.read(MAX_IPC_BYTES + 1)
            if len(data) > MAX_IPC_BYTES:
                return
            request = json.loads(data)
            _run_matching(request, emit)
        except Exception:
            # Parent classifies an interrupted protocol without leaking the SDK exception.
            return


def _stop(process):
    if process.poll() is None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=2)


def _receive(process, components, checked_at, metadata, timeout):
    result = MatchResult()
    deadline = time.monotonic() + timeout
    pending = None
    done = False
    buffer = bytearray()
    transferred = 0
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while not done:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            events = selector.select(remaining)
            if not events:
                break
            block = os.read(process.stdout.fileno(), 65536)
            if not block:
                break
            transferred += len(block)
            if transferred > MAX_IPC_BYTES:
                break
            buffer.extend(block)
            while b"\n" in buffer:
                line, _, rest = buffer.partition(b"\n")
                buffer = bytearray(rest)
                try:
                    message = json.loads(line)
                    kind = message["kind"]
                    if kind == "limitation" and set(message) == {"kind", "value"}:
                        if message["value"] != EXCLUDED_PROJECTS_LIMITATION:
                            raise ValueError("Invalid limitation")
                        if message["value"] not in result.limitations:
                            result.limitations.append(message["value"])
                    elif kind == "started" and set(message) == {"kind", "component"}:
                        if (
                            pending is not None
                            or message["component"] != components[len(result.results)]
                        ):
                            raise ValueError("Unexpected component")
                        pending = message["component"]
                    elif kind == "result" and set(message) == {"kind", "value"}:
                        record = message["value"]
                        if pending is None:
                            raise ValueError("Unrequested result")
                        failure = record.get("failure")
                        if failure not in (None, "unsupported", "collection_error"):
                            raise ValueError("Invalid failure")
                        projects = record["projects"]
                        if (
                            not isinstance(projects, list)
                            or len(projects) > 10_000
                            or any(
                                p != {"id": p["id"], "name": metadata[p["id"]]["name"]}
                                for p in projects
                            )
                            or len({p["id"] for p in projects}) != len(projects)
                        ):
                            raise ValueError("Invalid project metadata")
                        if record != candidate_record(pending, checked_at, projects, failure):
                            raise ValueError("Invalid candidate record")
                        result.results.append(record)
                        pending = None
                    elif kind == "done" and set(message) == {"kind"}:
                        if pending is not None or len(result.results) != len(components):
                            raise ValueError("Premature completion")
                        done = True
                        break
                    else:
                        raise ValueError("Invalid protocol")
                except (
                    ValueError,
                    KeyError,
                    TypeError,
                    IndexError,
                    RecursionError,
                    UnicodeDecodeError,
                ):
                    if pending is None and len(result.results) < len(components):
                        pending = components[len(result.results)]
                    return _incomplete(result, pending, checked_at)
    if not done:
        return _incomplete(result, pending, checked_at)
    return result


def _incomplete(result, pending, checked_at):
    if pending is not None:
        result.results.append(candidate_record(pending, checked_at, [], "collection_error"))
    result.limitations.append("SDK matching did not complete; later components were not checked")
    return result


def match_projects(
    platform: str,
    projects: list[dict],
    components: list[dict],
    checked_at: str | None,
    *,
    timeout: float = 30,
) -> MatchResult:
    """Run the pinned helper with JSON-only IPC and retain completed candidates.

    The timeout covers the entire matching process, including SDK imports. Source
    definitions never enter returned records. API completion is a separate concern.
    """
    projects, limitations = sanitize_projects(platform, projects)
    components = validate_components(platform, components)
    if (
        checked_at is not None
        and (not isinstance(checked_at, str) or len(checked_at) > 64)
        or not 0 < timeout <= 30
    ):
        raise InvalidSnapshotError("Workspace SDK timestamp or timeout is invalid")
    request = bounded_json(
        {
            "platform": platform,
            "projects": projects,
            "components": components,
            "checked_at": checked_at,
        }
    )
    # A new interpreter receives neither arbitrary parent environment nor auth config.
    environment = {
        key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR") if key in os.environ
    }
    environment.update(
        {
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    with tempfile.TemporaryFile() as source:
        source.write(request)
        source.seek(0)
        with subprocess.Popen(
            [sys.executable, "-m", __name__],
            stdin=source,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=environment,
            start_new_session=True,
        ) as process:
            try:
                result = _receive(
                    process, components, checked_at, {p["id"]: p for p in projects}, timeout
                )
            finally:
                _stop(process)
    result.limitations = list(dict.fromkeys(limitations + result.limitations))
    return result


if __name__ == "__main__":
    _child()
