"""Opt-in usage argument validation and staged offline artifact persistence."""

from __future__ import annotations

import importlib.metadata
import os
import stat
import tempfile
from pathlib import Path

from sdr_visualizer.cli.output_safety import paths_alias
from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.input.loader import STDIN_TOKEN, list_snapshot_candidates


def alias(left, right):
    result = paths_alias(left, right)
    if result is None:
        raise InvalidSnapshotError("could not verify Workspace file identity")
    return result


def outside_snapshot_directories(path, args, role):
    for raw in (args.path, args.compare_to):
        if not raw or raw == STDIN_TOKEN:
            continue
        directory = Path(raw)
        if not directory.is_dir():
            continue
        try:
            contained = path.absolute().is_relative_to(
                directory.absolute()
            ) or path.resolve().is_relative_to(directory.resolve())
        except (OSError, RuntimeError) as exc:
            raise InvalidSnapshotError("could not verify Workspace file identity") from exc
        if contained or any(alias(path, p) for p in list_snapshot_candidates(directory)):
            raise InvalidSnapshotError(f"{role} must be outside snapshot directories")


def validate_options(args):
    """Read file metadata only; credentials remain private to the API child."""
    collect_only = (
        args.workspace_usage_config,
        args.workspace_usage_scope,
        args.workspace_usage_project,
        args.workspace_usage_component,
        args.workspace_usage_output,
    )
    if not args.collect_workspace_usage:
        if any(value is not None for value in collect_only):
            raise InvalidSnapshotError(
                "Workspace collection options require --collect-workspace-usage"
            )
        return
    from sdr_visualizer.usage.normalize import identifier, validate_components

    if not identifier(args.workspace_usage_org):
        raise InvalidSnapshotError("--collect-workspace-usage requires --workspace-usage-org")
    platform = "cja" if args.dataview else "aa" if args.rsid else args.platform
    if args.workspace_usage_company is not None and not identifier(args.workspace_usage_company):
        raise InvalidSnapshotError("Invalid Workspace company context")
    if platform == "aa" and args.workspace_usage_company is None:
        raise InvalidSnapshotError("AA collection requires --workspace-usage-company")
    if platform == "cja" and args.workspace_usage_company is not None:
        raise InvalidSnapshotError("CJA collection does not accept --workspace-usage-company")
    if args.workspace_usage_project is not None:
        if args.workspace_usage_scope is not None:
            raise InvalidSnapshotError("Workspace project IDs and scope are mutually exclusive")
        projects = args.workspace_usage_project
        if (
            len(projects) > 10000
            or len(set(projects)) != len(projects)
            or any(not identifier(p) for p in projects)
        ):
            raise InvalidSnapshotError("Invalid explicit Workspace project scope")
    if args.workspace_usage_component is not None:
        components = []
        for value in args.workspace_usage_component:
            kind, separator, identity = value.partition("=")
            if not separator:
                raise InvalidSnapshotError("Workspace components require TYPE=ID")
            components.append({"type": kind, "id": identity})
        # Use the CJA superset until adaptation establishes the actual platform.
        args.workspace_usage_component = validate_components(platform or "cja", components)
    if args.workspace_usage_config is not None:
        config = Path(args.workspace_usage_config)
        try:
            info = config.stat()
        except OSError as exc:
            raise InvalidSnapshotError("Workspace config requires a regular file") from exc
        if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
            raise InvalidSnapshotError("Workspace config requires a regular file of at most 64 KiB")
        outside_snapshot_directories(config, args, "Workspace config")
        for raw in (args.path, args.compare_to, args.workspace_usage):
            if raw and raw != STDIN_TOKEN and not Path(raw).is_dir() and alias(config, Path(raw)):
                raise InvalidSnapshotError("Workspace config aliases an input")
    if args.workspace_usage_output is not None:
        outside_snapshot_directories(
            Path(args.workspace_usage_output), args, "Workspace usage output"
        )
    if platform:
        validate_dependencies(platform)


def validate_dependencies(platform):
    from sdr_visualizer.usage.normalize import SDK_VERSIONS

    name, expected = SDK_VERSIONS[platform]
    try:
        version = importlib.metadata.version(name)
        importlib.metadata.version("requests")
    except importlib.metadata.PackageNotFoundError:
        raise InvalidSnapshotError(
            "Install the selected Workspace SDK extra before collection"
        ) from None
    if version != expected:
        raise InvalidSnapshotError("Workspace collection requires the pinned selected SDK version")


def collection_options(args):
    return {
        "organization_context": args.workspace_usage_org,
        "company_context": args.workspace_usage_company,
        "components": args.workspace_usage_component,
        "scope": args.workspace_usage_scope or "all",
        "project_ids": args.workspace_usage_project,
    }


def validate_destinations(outputs, protected, args):
    """Check every known destination before exporter/API work, without writes."""
    if args.workspace_usage_config is not None:
        protected = [*protected, ("Workspace config", Path(args.workspace_usage_config))]
    for index, (role, path) in enumerate(outputs):
        if role == "Workspace usage output":
            outside_snapshot_directories(path, args, role)
        for other_role, other in [*protected, *outputs[:index]]:
            if alias(path, other):
                raise InvalidSnapshotError(f"{role} aliases {other_role}; choose distinct paths")
        if not path.parent.is_dir() or path.is_dir():
            raise InvalidSnapshotError(
                f"{role} requires a file destination in an existing directory"
            )


def write_artifacts(artifacts):
    """Stage all UTF-8 files before replacing any final destination.

    A replacement failure can leave earlier complete files installed. Temporary
    files are always removed, and callers print success only after this returns.
    """
    staged = []
    current = None
    try:
        for current, text, private in artifacts:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=current.parent,
                prefix=f".{current.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                staged.append((temporary, current))
                if not private and current.exists():
                    os.chmod(temporary, stat.S_IMODE(current.stat().st_mode))
                handle.write(text)
        for temporary, current in staged:
            os.replace(temporary, current)
    except OSError as exc:
        raise OSError(f"could not write {current}: {exc}") from exc
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
