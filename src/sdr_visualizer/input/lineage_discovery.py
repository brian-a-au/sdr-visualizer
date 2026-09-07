"""Content-free saved/live acquisition boundary for CJA lineage discovery."""

from __future__ import annotations

import json
import math
import os
import pwd
import re
import selectors
import signal
import stat
import subprocess
import time
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from sdr_visualizer.adapters.cja_lineage import adapt
from sdr_visualizer.core.lineage import LineageTopology

DEFAULT_STDOUT_LIMIT = 64 * 1024 * 1024
DEFAULT_STDERR_LIMIT = 1024 * 1024
DEFAULT_SAVED_LIMIT = DEFAULT_STDOUT_LIMIT
DEFAULT_TIMEOUT_SECONDS = 600.0

_READ_SIZE = 64 * 1024
_VERSION_OUTPUT = re.compile(rb"\Acja_auto_sdr (?:3\.11\.8|3\.12\.0)(?:\r?\n)?\Z")
_VERSION_OUTPUT_LIMIT = 8 * 1024
_VERSION_TIMEOUT_SECONDS = 10.0
_PROFILE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_MAX_CONFIG_PATH_LENGTH = 4_096
_CREDENTIAL_ENVIRONMENT_KEYS = (
    "CJA_PROFILE",
    "ORG_ID",
    "CLIENT_ID",
    "SECRET",
    "SCOPES",
    "SANDBOX",
)


class LineageDiscoveryFailureCode(StrEnum):
    """Stable acquisition failures that never carry external content."""

    SAVED_READ_FAILED = "saved-read-failed"
    SAVED_TOO_LARGE = "saved-too-large"
    EXECUTABLE_INVALID = "executable-invalid"
    EXECUTABLE_VERSION_MISMATCH = "executable-version-mismatch"
    SELECTOR_INVALID = "selector-invalid"
    PROCESS_FAILED = "process-failed"
    STDOUT_LIMIT_EXCEEDED = "stdout-limit-exceeded"
    STDERR_LIMIT_EXCEEDED = "stderr-limit-exceeded"
    TIMEOUT = "timeout"
    INVALID_UTF8 = "invalid-utf8"
    INVALID_JSON = "invalid-json"
    INVALID_STRUCTURE = "invalid-structure"


@dataclass(frozen=True, slots=True)
class LineageDiscoveryFailure:
    """A deliberately content-free acquisition result."""

    code: LineageDiscoveryFailureCode

    def __str__(self) -> str:
        return self.code.value

    def __repr__(self) -> str:
        return f"LineageDiscoveryFailure(code={self.code.value!r})"


LineageDiscoveryResult = LineageTopology | LineageDiscoveryFailure


@dataclass(frozen=True, slots=True)
class _Capture:
    stdout: bytes
    returncode: int


def acquire_saved(
    path: str | os.PathLike[str],
    *,
    scope_label: str,
    max_bytes: int = DEFAULT_SAVED_LIMIT,
) -> LineageDiscoveryResult:
    """Read, bound, decode, parse, and normalize one saved discovery export."""
    if not _positive_limit(max_bytes):
        return LineageDiscoveryFailure(LineageDiscoveryFailureCode.SAVED_TOO_LARGE)
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | os.O_NONBLOCK
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        descriptor = os.open(os.fspath(path), flags)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return LineageDiscoveryFailure(LineageDiscoveryFailureCode.SAVED_READ_FAILED)
        chunks = bytearray()
        while True:
            chunk = os.read(descriptor, min(_READ_SIZE, max_bytes - len(chunks) + 1))
            if not chunk:
                break
            if len(chunk) > max_bytes - len(chunks):
                return LineageDiscoveryFailure(LineageDiscoveryFailureCode.SAVED_TOO_LARGE)
            chunks.extend(chunk)
    except Exception:
        return LineageDiscoveryFailure(LineageDiscoveryFailureCode.SAVED_READ_FAILED)
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
    return _decode_and_normalize(bytes(chunks), scope_label=scope_label)


def acquire_live(
    executable: str | os.PathLike[str],
    *,
    scope_label: str,
    profile: str | None = None,
    config_file: str | os.PathLike[str] | None = None,
    stdout_limit: int = DEFAULT_STDOUT_LIMIT,
    stderr_limit: int = DEFAULT_STDERR_LIMIT,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> LineageDiscoveryResult:
    """Run verified CJA discovery and normalize its bounded stdout.

    Executable identity and version are checked in a credential-free process
    before profile/config selectors or the live environment are constructed.
    """
    if (
        not _positive_limit(stdout_limit)
        or not _positive_limit(stderr_limit)
        or not isinstance(timeout_seconds, (int, float))
        or isinstance(timeout_seconds, bool)
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        return LineageDiscoveryFailure(LineageDiscoveryFailureCode.PROCESS_FAILED)

    selectors_result = _validate_selectors(profile, config_file)
    if selectors_result is None:
        return LineageDiscoveryFailure(LineageDiscoveryFailureCode.SELECTOR_INVALID)
    normalized_profile, normalized_config = selectors_result

    executable_path = Path(executable)
    verification = _verify_executable(executable_path)
    if verification is not None:
        return verification

    argv = [str(executable_path)]
    if normalized_profile is not None:
        argv.extend(("--profile", normalized_profile))
    elif normalized_config is not None:
        argv.extend(("--config-file", normalized_config))
    argv.extend(("--list-datasets", "--format", "json", "--output", "-", "--quiet"))

    captured = _run_bounded(
        argv,
        env=_live_environment(
            explicit_profile=normalized_profile is not None,
            fallback_discovery=normalized_profile is None and normalized_config is None,
        ),
        stdout_limit=stdout_limit,
        stderr_limit=stderr_limit,
        timeout_seconds=float(timeout_seconds),
    )
    if isinstance(captured, LineageDiscoveryFailure):
        return captured
    if captured.returncode != 0:
        return LineageDiscoveryFailure(LineageDiscoveryFailureCode.PROCESS_FAILED)
    return _decode_and_normalize(captured.stdout, scope_label=scope_label)


def _verify_executable(path: Path) -> LineageDiscoveryFailure | None:
    if not path.is_absolute():
        return LineageDiscoveryFailure(LineageDiscoveryFailureCode.EXECUTABLE_INVALID)
    try:
        metadata = os.lstat(path)
    except Exception:
        return LineageDiscoveryFailure(LineageDiscoveryFailureCode.EXECUTABLE_INVALID)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or not metadata.st_mode & stat.S_IXUSR
    ):
        return LineageDiscoveryFailure(LineageDiscoveryFailureCode.EXECUTABLE_INVALID)

    captured = _run_bounded(
        [str(path), "--version"],
        env=_probe_environment(),
        stdout_limit=_VERSION_OUTPUT_LIMIT,
        stderr_limit=_VERSION_OUTPUT_LIMIT,
        timeout_seconds=_VERSION_TIMEOUT_SECONDS,
    )
    if isinstance(captured, LineageDiscoveryFailure) or captured.returncode != 0:
        return LineageDiscoveryFailure(LineageDiscoveryFailureCode.EXECUTABLE_INVALID)
    if _VERSION_OUTPUT.fullmatch(captured.stdout) is None:
        return LineageDiscoveryFailure(LineageDiscoveryFailureCode.EXECUTABLE_VERSION_MISMATCH)
    return None


def _validate_selectors(
    profile: object, config_file: str | os.PathLike[str] | None
) -> tuple[str | None, str | None] | None:
    if profile is not None and (
        not isinstance(profile, str) or _PROFILE.fullmatch(profile) is None
    ):
        return None
    if profile is not None and config_file is not None:
        return None
    if config_file is None:
        return profile, None
    try:
        raw_config = os.fspath(config_file)
    except Exception:
        return None
    if not isinstance(raw_config, str):
        return None
    if (
        not raw_config
        or len(raw_config) > _MAX_CONFIG_PATH_LENGTH
        or "\x00" in raw_config
        or any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in raw_config)
        or not Path(raw_config).is_absolute()
    ):
        return None
    return profile, raw_config


def _probe_environment() -> dict[str, str]:
    return {"LANG": "C", "LC_ALL": "C", "PATH": os.defpath}


def _live_environment(*, explicit_profile: bool, fallback_discovery: bool) -> dict[str, str]:
    environment = _probe_environment()
    if explicit_profile or fallback_discovery:
        with suppress(Exception):
            environment["HOME"] = pwd.getpwuid(os.getuid()).pw_dir
    if fallback_discovery:
        for name in _CREDENTIAL_ENVIRONMENT_KEYS:
            value = os.environ.get(name)
            if value is not None:
                environment[name] = value
    return environment


def _run_bounded(
    argv: list[str],
    *,
    env: dict[str, str],
    stdout_limit: int,
    stderr_limit: int,
    timeout_seconds: float,
) -> _Capture | LineageDiscoveryFailure:
    process: subprocess.Popen[bytes] | None = None
    selector = selectors.DefaultSelector()
    stdout = bytearray()
    stderr = bytearray()
    deadline = time.monotonic() + timeout_seconds
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            shell=False,
            start_new_session=True,
            bufsize=0,
        )
        if process.stdout is None or process.stderr is None:
            _terminate_process_tree(process)
            return LineageDiscoveryFailure(LineageDiscoveryFailureCode.PROCESS_FAILED)
        for stream, channel in ((process.stdout, "stdout"), (process.stderr, "stderr")):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, channel)

        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_process_tree(process)
                return LineageDiscoveryFailure(LineageDiscoveryFailureCode.TIMEOUT)
            for key, _ in selector.select(remaining):
                try:
                    chunk = os.read(key.fileobj.fileno(), _READ_SIZE)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                target = stdout if key.data == "stdout" else stderr
                limit = stdout_limit if key.data == "stdout" else stderr_limit
                if len(chunk) > limit - len(target):
                    _terminate_process_tree(process)
                    code = (
                        LineageDiscoveryFailureCode.STDOUT_LIMIT_EXCEEDED
                        if key.data == "stdout"
                        else LineageDiscoveryFailureCode.STDERR_LIMIT_EXCEEDED
                    )
                    return LineageDiscoveryFailure(code)
                target.extend(chunk)

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _terminate_process_tree(process)
            return LineageDiscoveryFailure(LineageDiscoveryFailureCode.TIMEOUT)
        returncode = process.wait(timeout=remaining)
        return _Capture(bytes(stdout), returncode)
    except subprocess.TimeoutExpired:
        if process is not None:
            _terminate_process_tree(process)
        return LineageDiscoveryFailure(LineageDiscoveryFailureCode.TIMEOUT)
    except Exception:
        if process is not None:
            _terminate_process_tree(process)
        return LineageDiscoveryFailure(LineageDiscoveryFailureCode.PROCESS_FAILED)
    finally:
        selector.close()
        if process is not None:
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    with suppress(Exception):
                        stream.close()
            if process.poll() is None:
                _terminate_process_tree(process)


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        with suppress(OSError):
            process.terminate()
    with suppress(subprocess.TimeoutExpired, OSError):
        process.wait(timeout=0.2)
    # The parent may exit on SIGTERM while a descendant ignores it. Always
    # follow with a group-wide SIGKILL so the whole capture tree is bounded.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        if process.poll() is None:
            with suppress(OSError):
                process.kill()
    if process.poll() is None:
        with suppress(subprocess.TimeoutExpired, OSError):
            process.wait(timeout=1.0)


def _decode_and_normalize(raw: bytes, *, scope_label: str) -> LineageDiscoveryResult:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError:
        return LineageDiscoveryFailure(LineageDiscoveryFailureCode.INVALID_UTF8)
    try:
        value: Any = json.loads(text)
    except (json.JSONDecodeError, ValueError, RecursionError):
        return LineageDiscoveryFailure(LineageDiscoveryFailureCode.INVALID_JSON)
    try:
        return adapt(value, scope_label=scope_label)
    except Exception:
        return LineageDiscoveryFailure(LineageDiscoveryFailureCode.INVALID_STRUCTURE)


def _positive_limit(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


__all__ = [
    "DEFAULT_SAVED_LIMIT",
    "DEFAULT_STDERR_LIMIT",
    "DEFAULT_STDOUT_LIMIT",
    "DEFAULT_TIMEOUT_SECONDS",
    "LineageDiscoveryFailure",
    "LineageDiscoveryFailureCode",
    "LineageDiscoveryResult",
    "acquire_live",
    "acquire_saved",
]
