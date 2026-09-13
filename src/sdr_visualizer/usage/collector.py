"""Optional bounded API acquisition; pure report rendering never imports SDKs."""

from __future__ import annotations

import contextlib
import importlib.metadata
import os
import selectors
import signal
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.core.workspace_usage import (
    CLOCK_REVERSAL_LIMITATION,
    NO_RESULTS_LIMITATION,
    bind_workspace_usage,
    component_inventory,
    snapshot_digest,
)
from sdr_visualizer.usage import aa_api, auth, cja_api
from sdr_visualizer.usage.normalize import (
    CANDIDATE_LIMITATION,
    EXCLUDED_PROJECTS_LIMITATION,
    MAX_IPC_BYTES,
    SDK_VERSIONS,
    bounded_json,
    candidate_record,
    identifier,
    sanitize_projects,
    validate_components,
)
from sdr_visualizer.usage.sdk_worker import match_projects
from sdr_visualizer.usage.transport import BoundedTransport, TransportError, decode_json

LIMITATIONS = {
    "index": "Workspace project index traversal was incomplete",
    "detail": "Some Workspace project details were unavailable or inconsistent",
    "cap": "Workspace project collection reached its source-data budget",
    "worker": "Workspace API collection was interrupted or exceeded its deadline",
    "access": "Workspace resource inaccessible",
    "error": "Workspace API collection failed",
}


def _now():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def preflight_collection(
    implementation,
    *,
    organization_context,
    company_context=None,
    components=None,
    scope="all",
    project_ids=None,
):
    """Validate selection and dependencies without credentials or network access."""
    platform = implementation.platform
    if platform not in SDK_VERSIONS or not identifier(organization_context):
        raise InvalidSnapshotError("Invalid Workspace platform or organization context")
    if (platform == "aa" and not identifier(company_context)) or (
        platform == "cja" and company_context is not None
    ):
        raise InvalidSnapshotError("Invalid Workspace company context")
    if not identifier(implementation.instance_id) or scope not in ("all", "owned", "shared"):
        raise InvalidSnapshotError("Invalid Workspace instance or scope")
    if project_ids is not None and (
        not isinstance(project_ids, list)
        or not 1 <= len(project_ids) <= 10000
        or any(not identifier(p) for p in project_ids)
        or len(set(project_ids)) != len(project_ids)
        or scope != "all"
    ):
        raise InvalidSnapshotError("Invalid explicit Workspace project scope")
    inventory = component_inventory(implementation)
    selected = validate_components(platform, inventory if components is None else components)
    counts = Counter(c["id"] for c in inventory)
    if any(c not in inventory or counts[c["id"]] != 1 for c in selected):
        raise InvalidSnapshotError("Unknown or ambiguous Workspace component identity")
    name, version = SDK_VERSIONS[platform]
    try:
        installed = importlib.metadata.version(name)
        importlib.metadata.version("requests")
    except importlib.metadata.PackageNotFoundError:
        raise InvalidSnapshotError(
            "Install the selected Workspace SDK extra before collection"
        ) from None
    if installed != version:
        raise InvalidSnapshotError("Workspace collection requires the pinned selected SDK version")
    return selected


def _initial(scope, project_ids, started_at):
    return {
        "status": "partial",
        "started_at": started_at,
        "finished_at": started_at,
        "include_type": "explicit" if project_ids is not None else scope,
        "request_attempts": 0,
        "pages_fetched": 0,
        "projects_discovered": len(project_ids) if project_ids is not None else 0,
        "projects_fetched": 0,
        "projects_failed": 0,
        "limitations": [],
    }


def _limit(retrieval, value):
    if value not in retrieval["limitations"]:
        retrieval["limitations"].append(value)


def _metadata(value):
    if not isinstance(value, dict) or not identifier(value.get("id")):
        raise TransportError("Workspace project identity is malformed")
    if "name" not in value or not (
        value["name"] is None or isinstance(value["name"], str) and 1 <= len(value["name"]) <= 256
    ):
        raise TransportError("Workspace project name is malformed")
    if (
        "modified" not in value
        or not isinstance(value["modified"], str)
        or not 1 <= len(value["modified"]) <= 256
    ):
        raise TransportError("Workspace project revision is malformed")
    # Validate scalar Unicode even for synthetic/injected transports.
    bounded_json({key: value[key] for key in ("id", "name", "modified")}, 4096)
    return {key: value[key] for key in ("id", "name", "modified")}


def _page(data, number):
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("content"), list)
        or len(data["content"]) > 50
    ):
        raise TransportError("Workspace project index is malformed")
    if (
        any(
            type(data.get(k)) is not int or data[k] < 0
            for k in ("number", "totalPages", "totalElements")
        )
        or type(data.get("lastPage")) is not bool
    ):
        raise TransportError("Workspace project pagination is malformed")
    total, pages = data["totalElements"], data["totalPages"]
    if (
        data["number"] != number
        or total > 10000000
        or pages > 10000000
        or pages != (total + 49) // 50
        or data["lastPage"] != (number >= pages - 1)
        or (total and number >= pages)
    ):
        raise TransportError("Workspace project pagination is inconsistent")
    expected = min(50, max(0, total - 50 * number))
    if len(data["content"]) != expected:
        raise TransportError("Workspace project page count is inconsistent")
    rows, invalid_ids, malformed = [], set(), False
    for project in data["content"]:
        try:
            rows.append(_metadata(project))
        except (TransportError, InvalidSnapshotError):
            malformed = True
            if isinstance(project, dict) and identifier(project.get("id")):
                invalid_ids.add(project["id"])
    return rows, (pages, total), data["lastPage"], invalid_ids, malformed


def collect_api(
    transport,
    headers,
    *,
    platform,
    instance_id,
    org_id,
    company_id=None,
    scope="all",
    project_ids=None,
    emit=None,
    started_at=None,
):
    """Run provider requests under an already installed guard (also fakeable in tests)."""
    retrieval = _initial(scope, project_ids, started_at or _now())
    projects, receipts, index = [], [], {}
    matching_limitations = []
    source_bytes = 0
    last_receipt = retrieval["started_at"]
    failure = None
    index_complete = project_ids is not None

    def progress(received_at=None, project=None):
        nonlocal last_receipt
        if received_at is not None:
            if received_at < last_receipt:
                _limit(retrieval, CLOCK_REVERSAL_LIMITATION)
            last_receipt = received_at
        retrieval["request_attempts"] = transport.request_attempts
        retrieval["finished_at"] = _now()
        if (
            retrieval["finished_at"] < last_receipt
            or retrieval["finished_at"] < retrieval["started_at"]
        ):
            _limit(retrieval, CLOCK_REVERSAL_LIMITATION)
        if emit:
            emit({"kind": "progress", "retrieval": retrieval.copy()})
            if project is not None:
                emit({"kind": "project", "project": project, "received_at": received_at})

    try:
        provider = cja_api if platform == "cja" else aa_api
        receipt = provider.verify_identity(transport, headers, instance_id, org_id, company_id)
        progress(receipt.received_at)
        if project_ids is None:
            totals = None
            previous_ids = set()
            invalid_ids = set()
            for number in range(20):
                params = {
                    "page": number,
                    "limit": 50,
                    "pagination": "true",
                    "expansion": "modified",
                }
                if scope != "owned":
                    params["includeType"] = scope
                try:
                    receipt = transport.get_json(
                        transport.route_url("projects"), headers=headers, params=params
                    )
                    rows, new_totals, last, bad_ids, malformed = _page(receipt.data, number)
                    invalid_ids.update(bad_ids)
                    if totals is not None and totals != new_totals:
                        raise TransportError("Workspace project totals changed")
                    totals = new_totals
                    retrieval["pages_fetched"] += 1
                    conflicts = False
                    for row in rows:
                        prior = index.get(row["id"])
                        if prior is not None and prior != row:
                            conflicts = True
                            invalid_ids.add(row["id"])
                        if prior is None:
                            index[row["id"]] = row
                    for bad_id in invalid_ids:
                        index.pop(bad_id, None)
                    retrieval["projects_discovered"] = len(set(index) | invalid_ids)
                    progress(receipt.received_at)
                    if (
                        conflicts
                        or malformed
                        or (last and len(index) != totals[1])
                        or (number and rows and all(row["id"] in previous_ids for row in rows))
                    ):
                        raise TransportError("Workspace project index identities conflict")
                    previous_ids = set(index)
                    if last:
                        index_complete = True
                        break
                except TransportError as exc:
                    failure = exc.failure
                    _limit(retrieval, LIMITATIONS["index"])
                    break
            if not index_complete:
                _limit(retrieval, LIMITATIONS["index"])
        else:
            index = dict.fromkeys(sorted(project_ids))
        if len(index) > 200:
            _limit(retrieval, LIMITATIONS["cap"])
        for identity in sorted(index)[:200]:
            attempts_before = transport.request_attempts
            fetched = False
            try:
                receipt = transport.get_json(
                    transport.route_url("project", identity),
                    headers=headers,
                    params={"expansion": "definition,externalReferences,modified"},
                )
                metadata = _metadata(receipt.data)
                if metadata["id"] != identity or (
                    index[identity] is not None and metadata != index[identity]
                ):
                    raise TransportError("Workspace project detail identity conflicts")
                clean, excluded = sanitize_projects(platform, [receipt.data])
                # Successful API retrieval and SDK parser coverage are separate.
                size = len(bounded_json(clean[0])) if clean else 0
                retrieval["projects_fetched"] += 1
                fetched = True
                if excluded:
                    if not matching_limitations:
                        matching_limitations.append(EXCLUDED_PROJECTS_LIMITATION)
                        if emit:
                            emit({"kind": "limitation", "value": EXCLUDED_PROJECTS_LIMITATION})
                    progress(receipt.received_at)
                    continue
                if source_bytes + size > MAX_IPC_BYTES - 65536:
                    _limit(retrieval, LIMITATIONS["cap"])
                    progress(receipt.received_at)
                    break
                source_bytes += size
                projects.append(clean[0])
                receipts.append(receipt.received_at)
                progress(receipt.received_at, clean[0])
            except (TransportError, InvalidSnapshotError) as exc:
                failure = exc.failure if isinstance(exc, TransportError) else "collection_error"
                if transport.request_attempts > attempts_before and not fetched:
                    retrieval["projects_failed"] += 1
                _limit(retrieval, LIMITATIONS["detail"])
                progress()
                if (
                    transport.request_attempts == attempts_before
                    or transport.request_attempts >= 256
                ):
                    break
        if not index_complete or retrieval["projects_fetched"] != retrieval["projects_discovered"]:
            _limit(retrieval, LIMITATIONS["index"])
    except TransportError as exc:
        failure = exc.failure
        _limit(
            retrieval,
            LIMITATIONS["access"] if failure == "permission_denied" else LIMITATIONS["error"],
        )
    progress()
    if CLOCK_REVERSAL_LIMITATION in retrieval["limitations"]:
        retrieval["started_at"] = retrieval["finished_at"] = None
    retrieval["status"] = "partial" if retrieval["limitations"] else "complete"
    if not projects and retrieval["status"] != "complete":
        retrieval["status"] = "failed"
        failure = failure or "collection_error"
    return {
        "retrieval": retrieval,
        "projects": projects,
        "checked_at": min(receipts)
        if receipts
        else last_receipt
        if retrieval["status"] == "complete" and retrieval["projects_discovered"] == 0
        else None,
        "failure": failure or ("unsupported" if matching_limitations and not projects else None),
        "matching_limitations": matching_limitations,
    }


def _child():
    output = sys.stdout.buffer

    def emit(message):
        output.write(bounded_json(message) + b"\n")
        output.flush()

    request = decode_json(sys.stdin.buffer.read(MAX_IPC_BYTES + 1), max_depth=10, max_nodes=25000)
    started = _now()
    transport = BoundedTransport(
        request["platform"],
        request["company_id"],
        on_attempt=lambda count: emit({"kind": "attempt", "count": count}),
    )
    try:
        with auth.quiet_sdk(), transport:
            credentials = auth.resolve_credentials(
                request["config_path"], expected_org=request["org_id"]
            )
            client = auth.initialize_sdk(
                request["platform"], credentials, transport, request["company_id"]
            )
            result = collect_api(
                transport,
                client.header,
                platform=request["platform"],
                instance_id=request["instance_id"],
                org_id=request["org_id"],
                company_id=request["company_id"],
                scope=request["scope"],
                project_ids=request["project_ids"],
                emit=emit,
                started_at=started,
            )
            result.pop("projects")
            result.pop("matching_limitations")
            emit({"kind": "done", **result})
    except InvalidSnapshotError:
        emit({"kind": "input_error"})
    except Exception as exc:
        retrieval = _initial(request["scope"], request["project_ids"], started)
        retrieval.update(
            status="failed",
            finished_at=_now(),
            request_attempts=transport.request_attempts,
            limitations=[LIMITATIONS["error"]],
        )
        if retrieval["finished_at"] < started:
            retrieval.update(started_at=None, finished_at=None)
            retrieval["limitations"].append(CLOCK_REVERSAL_LIMITATION)
        emit(
            {
                "kind": "done",
                "retrieval": retrieval,
                "checked_at": None,
                "failure": exc.failure if isinstance(exc, TransportError) else "collection_error",
            }
        )


def _stop(process):
    if process.poll() is None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=2)


def _validate_progress(value, previous, scope, project_ids):
    if not isinstance(value, dict) or set(value) != set(previous):
        raise ValueError
    for key, cap in (
        ("request_attempts", 256),
        ("pages_fetched", 20),
        ("projects_discovered", 10000 if project_ids is not None else 1000),
        ("projects_fetched", 200),
        ("projects_failed", 200),
    ):
        if type(value[key]) is not int or not previous[key] <= value[key] <= cap:
            raise ValueError
    if value["projects_failed"] + value["projects_fetched"] > min(
        200, value["projects_discovered"]
    ):
        raise ValueError
    if (
        value["pages_fetched"] + value["projects_fetched"] + value["projects_failed"]
        > value["request_attempts"]
        or project_ids is not None
        and value["pages_fetched"] != 0
    ):
        raise ValueError
    if value["include_type"] != ("explicit" if project_ids is not None else scope) or value[
        "status"
    ] not in ("partial", "failed", "complete"):
        raise ValueError
    if (
        not isinstance(value["limitations"], list)
        or len(value["limitations"]) > 20
        or any(
            v not in (*LIMITATIONS.values(), CLOCK_REVERSAL_LIMITATION)
            for v in value["limitations"]
        )
    ):
        raise ValueError
    for key in ("started_at", "finished_at"):
        stamp = value[key]
        if stamp is not None and (
            not isinstance(stamp, str)
            or datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%dT%H:%M:%SZ")
            != stamp
        ):
            raise ValueError
    return value


def _receive(process, request, timeout=180):
    retrieval = _initial(request["scope"], request["project_ids"], _now())
    projects, receipts, buffer = [], [], bytearray()
    matching_limitations = []
    deadline, transferred = time.monotonic() + timeout, 0
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while time.monotonic() < deadline:
                if not selector.select(max(0, deadline - time.monotonic())):
                    break
                block = os.read(process.stdout.fileno(), 65536)
                if not block:
                    break
                transferred += len(block)
                if transferred > MAX_IPC_BYTES:
                    break
                buffer.extend(block)
                while b"\n" in buffer:
                    line, _, buffer = buffer.partition(b"\n")
                    message = decode_json(line)
                    if not isinstance(message, dict):
                        raise ValueError
                    kind = message.get("kind")
                    if kind == "attempt" and set(message) == {"kind", "count"}:
                        count = message["count"]
                        if (
                            type(count) is not int
                            or count != retrieval["request_attempts"] + 1
                            or count > 256
                        ):
                            raise ValueError
                        retrieval["request_attempts"] = count
                        continue
                    if kind == "input_error" and set(message) == {"kind"}:
                        raise InvalidSnapshotError(
                            "Workspace authentication or environment identity is invalid"
                        )
                    if kind == "limitation" and message == {
                        "kind": "limitation",
                        "value": EXCLUDED_PROJECTS_LIMITATION,
                    }:
                        if not matching_limitations:
                            matching_limitations.append(EXCLUDED_PROJECTS_LIMITATION)
                        continue
                    if kind == "progress" and set(message) == {"kind", "retrieval"}:
                        retrieval = _validate_progress(
                            message["retrieval"],
                            retrieval,
                            request["scope"],
                            request["project_ids"],
                        )
                    elif kind == "project" and set(message) == {"kind", "project", "received_at"}:
                        clean, excluded = sanitize_projects(
                            request["platform"], [message["project"]]
                        )
                        stamp = message["received_at"]
                        if (
                            excluded
                            or clean[0] != message["project"]
                            or len(projects) >= 200
                            or any(p["id"] == clean[0]["id"] for p in projects)
                            or (
                                request["project_ids"] is not None
                                and clean[0]["id"] not in request["project_ids"]
                            )
                        ):
                            raise ValueError
                        if (
                            not isinstance(stamp, str)
                            or datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").strftime(
                                "%Y-%m-%dT%H:%M:%SZ"
                            )
                            != stamp
                        ):
                            raise ValueError
                        projects.append(clean[0])
                        receipts.append(stamp)
                    elif kind == "done" and set(message) == {
                        "kind",
                        "retrieval",
                        "checked_at",
                        "failure",
                    }:
                        retrieval = _validate_progress(
                            message["retrieval"],
                            retrieval,
                            request["scope"],
                            request["project_ids"],
                        )
                        if message["failure"] not in (
                            None,
                            "permission_denied",
                            "collection_error",
                            "unsupported",
                            "unknown",
                        ):
                            raise ValueError
                        checked = min(receipts) if receipts else message["checked_at"]
                        if checked is not None and (
                            not isinstance(checked, str)
                            or datetime.strptime(checked, "%Y-%m-%dT%H:%M:%SZ").strftime(
                                "%Y-%m-%dT%H:%M:%SZ"
                            )
                            != checked
                        ):
                            raise ValueError
                        return {
                            "retrieval": retrieval,
                            "projects": projects,
                            "checked_at": checked,
                            "failure": message["failure"],
                            "matching_limitations": matching_limitations,
                        }
                    else:
                        raise ValueError
    except (ValueError, TypeError, KeyError, IndexError, TransportError):
        # Malformed or failed worker output falls through to a bounded partial/failure
        # result below, retaining project observations that already passed validation.
        pass
    _limit(retrieval, LIMITATIONS["worker"])
    end = _now()
    if (
        retrieval["started_at"] is None
        or end < retrieval["started_at"]
        or CLOCK_REVERSAL_LIMITATION in retrieval["limitations"]
    ):
        retrieval["started_at"] = retrieval["finished_at"] = None
        _limit(retrieval, CLOCK_REVERSAL_LIMITATION)
    else:
        retrieval["finished_at"] = end
    retrieval["status"] = "partial" if projects else "failed"
    return {
        "retrieval": retrieval,
        "projects": projects,
        "checked_at": min(receipts) if receipts else None,
        "failure": "collection_error",
        "matching_limitations": matching_limitations,
    }


def _acquire(request):
    environment = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "WINDIR", "ORG_ID", "CLIENT_ID", "SECRET", "SCOPES")
        if key in os.environ
    }
    environment.update(
        PYTHONPATH=str(Path(__file__).resolve().parents[2]),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONIOENCODING="utf-8",
    )
    with tempfile.TemporaryFile() as source:
        source.write(bounded_json(request))
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
                return _receive(process, request)
            finally:
                _stop(process)


def collect_workspace_usage(
    implementation,
    *,
    organization_context,
    company_context=None,
    config_path=None,
    scope="all",
    project_ids=None,
    components=None,
):
    """Collect optional evidence; return the same bound contract as offline replay."""
    selected = preflight_collection(
        implementation,
        organization_context=organization_context,
        company_context=company_context,
        components=components,
        scope=scope,
        project_ids=project_ids,
    )
    request = {
        "platform": implementation.platform,
        "instance_id": implementation.instance_id,
        "org_id": organization_context,
        "company_id": company_context,
        "config_path": str(config_path) if config_path is not None else None,
        "scope": scope,
        "project_ids": project_ids,
    }
    acquired = _acquire(request)
    retrieval = acquired["retrieval"]
    limitations = list(retrieval["limitations"]) + acquired.get("matching_limitations", [])
    if acquired["projects"]:
        matches = match_projects(
            implementation.platform, acquired["projects"], selected, acquired["checked_at"]
        )
        results = matches.results
        limitations.extend(matches.limitations)
    elif retrieval["status"] == "complete" and retrieval["projects_discovered"] == 0:
        results = [candidate_record(c, acquired["checked_at"], []) for c in selected]
        limitations.append("No projects were visible in the checked project scope")
    else:
        results = []
    collection = {
        "status": "partial" if results or acquired["projects"] else "failed",
        "project_scope": {"kind": "explicit_projects", "project_ids": project_ids}
        if project_ids is not None
        else {"kind": "accessible_projects"},
        "permission_visibility": "limited",
        "limitations": list(dict.fromkeys(limitations + [CANDIDATE_LIMITATION])),
        "source": {
            "kind": "sdk_candidates",
            "sdk": SDK_VERSIONS[implementation.platform][0],
            "version": SDK_VERSIONS[implementation.platform][1],
        },
        "retrieval": retrieval,
    }
    if acquired["failure"] or collection["status"] == "failed":
        collection["failure"] = acquired["failure"] or "collection_error"
    if not results and collection["status"] == "partial":
        collection["limitations"].append(NO_RESULTS_LIMITATION)
    target = {
        "platform": implementation.platform,
        "ims_org_id": organization_context,
        "data_view_id" if implementation.platform == "cja" else "rsid": implementation.instance_id,
        "snapshot_digest": snapshot_digest(implementation.raw),
    }
    if implementation.platform == "aa":
        target["global_company_id"] = company_context
    return bind_workspace_usage(
        {
            "schema_version": 1,
            "target": target,
            "collection": collection,
            "requested_components": selected,
            "results": results,
        },
        implementation,
        organization_context=organization_context,
        company_context=company_context,
    )


if __name__ == "__main__":
    _child()
