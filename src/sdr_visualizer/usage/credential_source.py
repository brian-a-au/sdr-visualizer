"""Choose and describe the Workspace credential source in the main process.

The lookup order is ``--workspace-usage-config``, then ``--profile``, then the
``ORG_ID``, ``CLIENT_ID``, ``SECRET`` and ``SCOPES`` environment variables. A
profile is read here, because the API worker has no ``HOME``. Its four values
reach the worker in the worker's environment, never in its arguments.
"""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.usage import auth

# Letters, digits, dots, underscores and hyphens. Starts with a letter or digit.
PROFILE_NAME = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
PROFILE_NAME_RULE = (
    "a profile name holds letters, digits, dots, underscores and hyphens, "
    "starts with a letter or digit, and has 64 characters or fewer"
)
PROFILE_FOLDERS = {"aa": ".aa", "cja": ".cja"}
PROFILE_VARIABLES = {"aa": "AA_PROFILE", "cja": "CJA_PROFILE"}
MASK = "****"


class CredentialSourceError(InvalidSnapshotError):
    """A lookup failure with a code from the Adobe credentials standard."""

    def __init__(self, code, message, missing=()):
        super().__init__(message)
        self.code, self.missing = code, tuple(missing)


def mask_client_id(client_id):
    """Show the first 4 and last 4 characters. Hide 8 characters or fewer whole."""
    text = str(client_id)
    return MASK if len(text) <= 8 else f"{text[:4]}{MASK}{text[-4:]}"


def is_masked_client_id(value):
    """Accept only a value that mask_client_id returns for a client ID in use.

    The parent runs this on what the worker sends. A client ID in use holds no
    control character, so a value with one is rejected and cannot change the
    terminal display.
    """
    return (
        type(value) is str
        and (value == MASK or (len(value) == 12 and value[4:8] == MASK))
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )


def mask_secret(secret):
    """Show a secret that is set as four stars, whatever its length."""
    return MASK if secret else ""


def valid_profile_name(name):
    return isinstance(name, str) and PROFILE_NAME.fullmatch(name) is not None


def profile_path(name, platform, *, home=None):
    """Check the name, then build the path of the profile's config file."""
    if not valid_profile_name(name):
        raise CredentialSourceError(
            "invalid_profile_name", "Invalid profile name: " + PROFILE_NAME_RULE
        )
    root = Path.home() if home is None else Path(home)
    return root / PROFILE_FOLDERS[platform] / "orgs" / name / "config.json"


def readable_by_others(path):
    """Report a credential file that the group or other users can read."""
    if os.name == "nt":
        return False
    try:
        # os.stat follows a symlink, so the target's mode is the one checked.
        mode = os.stat(path).st_mode
    except OSError:
        return False
    return bool(mode & (stat.S_IRGRP | stat.S_IROTH))


@dataclass(frozen=True, repr=False)
class CredentialSource:
    kind: str  # "config", "profile" or "environment"
    path: Path | None = None
    profile: str | None = None
    # Set for a profile only: the values the main process hands to the worker.
    credentials: auth.Credentials | None = None
    warnings: tuple = field(default=())
    notices: tuple = field(default=())

    def __repr__(self):
        return f"CredentialSource({self.kind})"

    def describe(self, masked_client_id=None):
        if self.kind == "config":
            text = f"config file {self.path}"
        elif self.kind == "profile":
            text = f"profile {self.profile} ({self.path})"
        else:
            text = "environment variables ORG_ID, CLIENT_ID, SECRET and SCOPES"
        if masked_client_id is not None:
            text += f", client ID {masked_client_id}, secret {MASK}"
        return "Workspace credential source: " + text


def _file_warnings(path):
    """Return a list of (code, text) pairs: one pair, or none."""
    warnings = []
    if readable_by_others(path):
        warnings.append(
            (
                "file_readable_by_others",
                f"credential file {path} can be read by the group or by other users; "
                "run chmod 600 on it",
            )
        )
    return warnings


def select_source(
    platform, *, config_path=None, profile=None, expected_org, environ=None, home=None
):
    """Return the one source this run uses. Fields never mix between sources."""
    if config_path is not None and profile is not None:
        raise CredentialSourceError(
            "profile_and_config_both_given",
            "--profile and --workspace-usage-config cannot be used together",
        )
    if config_path is not None:
        # The worker reads the file. Only its mode is checked here.
        path = Path(config_path)
        return CredentialSource("config", path=path, warnings=tuple(_file_warnings(path)))
    if profile is not None:
        path = profile_path(profile, platform, home=home)
        if not path.is_file():
            raise CredentialSourceError("profile_not_found", f"Profile not found: {path}")
        source = auth.read_source_file(path, allowed=auth.PROFILE_KEYS)
        missing = [
            key
            for key in auth.FIELDS
            if source.get(key) is None or source.get(key) == "" or source.get(key) == []
        ]
        if missing:
            raise CredentialSourceError(
                "partial_source",
                f"Profile {profile} is missing these fields: {', '.join(missing)}",
                missing,
            )
        return CredentialSource(
            "profile",
            path=path,
            profile=profile,
            credentials=auth.validate_source(source, expected_org=expected_org),
            warnings=tuple(_file_warnings(path)),
        )
    env = os.environ if environ is None else environ
    variable = PROFILE_VARIABLES[platform]
    notices = ()
    if env.get(variable):
        notices = (
            (
                "profile_variable_not_used",
                f"{variable} is set and this release does not read it for Workspace usage. "
                "A later major release will use that profile before the environment "
                "variables. Pass --profile to use it now.",
            ),
        )
    return CredentialSource("environment", notices=notices)
