#!/usr/bin/env python3
"""Validate local links in every tracked Markdown document.

The checker deliberately uses Git's tracked-file list rather than the working
tree. That prevents public documentation from silently depending on ignored or
otherwise unpublished files that happen to exist in a maintainer checkout.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import SplitResult, unquote, urlsplit

INLINE_LINK_RE = re.compile(r"]\(\s*(?:<([^>]+)>|([^)\s]+))(?:\s+['\"].*?['\"])?\s*\)")
REFERENCE_DEFINITION_RE = re.compile(
    r"^\s{0,3}\[[^\]]+]:\s*(?:<([^>]+)>|(\S+))",
    re.MULTILINE,
)
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
EXPLICIT_ID_RE = re.compile(r"""(?:id|name)=["']([^"']+)["']""")
REMOTE_SCHEMES = {
    "data",
    "ftp",
    "http",
    "https",
    "irc",
    "mailto",
    "news",
    "tel",
}
REPOSITORY_URL_PREFIXES = (
    "/brian-a-au/sdr-visualizer/blob/main/",
    "/brian-a-au/sdr-visualizer/tree/main/",
)


def tracked_files(repo: Path) -> set[str]:
    """Return Git-tracked paths relative to *repo*."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return {
        path.decode("utf-8", errors="surrogateescape")
        for path in result.stdout.split(b"\0")
        if path
    }


def _without_fenced_code(text: str) -> str:
    """Blank fenced code while preserving source line numbers."""
    output: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        match = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker[0]
            elif marker[0] == fence:
                fence = None
            output.append("\n" if line.endswith("\n") else "")
        elif fence is None:
            output.append(line)
        else:
            output.append("\n" if line.endswith("\n") else "")
    return "".join(output)


def _github_slug(heading: str) -> str:
    heading = re.sub(r"<[^>]+>", "", heading)
    heading = re.sub(r"!\[([^\]]*)]\([^)]*\)", r"\1", heading)
    heading = re.sub(r"\[([^\]]+)]\([^)]*\)", r"\1", heading)
    heading = re.sub(r"[`*_~]", "", heading).strip().lower()
    heading = re.sub(r"[^\w\- ]", "", heading)
    return re.sub(r"\s+", "-", heading)


def markdown_anchors(path: Path) -> set[str]:
    """Return GitHub-style heading anchors and explicit HTML ids."""
    text = _without_fenced_code(path.read_text(encoding="utf-8"))
    anchors: set[str] = set(EXPLICIT_ID_RE.findall(text))
    counts: dict[str, int] = {}
    for line in text.splitlines():
        match = HEADING_RE.match(line)
        if not match:
            continue
        base = _github_slug(match.group(1))
        if not base:
            continue
        occurrence = counts.get(base, 0)
        counts[base] = occurrence + 1
        anchors.add(base if occurrence == 0 else f"{base}-{occurrence}")
    return anchors


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _is_tracked_target(relative: str, tracked_paths: set[str]) -> bool:
    if relative in tracked_paths:
        return True
    prefix = relative.rstrip("/") + "/"
    return any(path.startswith(prefix) for path in tracked_paths)


def _canonical_repository_path(split: SplitResult) -> str | None:
    """Map this repository's living ``main`` URLs back to checkout paths."""
    if split.scheme.lower() != "https" or split.netloc.lower() != "github.com":
        return None
    for prefix in REPOSITORY_URL_PREFIXES:
        if split.path.startswith(prefix):
            return unquote(split.path.removeprefix(prefix))
    return None


def _markdown_link_matches(text: str) -> tuple[str, list[re.Match[str]]]:
    text = _without_fenced_code(text)
    matches = list(INLINE_LINK_RE.finditer(text)) + list(REFERENCE_DEFINITION_RE.finditer(text))
    return text, sorted(matches, key=lambda item: item.start())


def markdown_link_targets(text: str) -> list[str]:
    """Return inline and reference-definition targets outside fenced code."""
    _, matches = _markdown_link_matches(text)
    return [(match.group(1) or match.group(2)).strip() for match in matches]


def check_markdown_file(
    source: Path,
    *,
    repo: Path,
    tracked_paths: set[str],
    anchor_cache: dict[Path, set[str]] | None = None,
) -> list[str]:
    """Return actionable local-link errors for one Markdown file."""
    repo = repo.resolve()
    source = source.resolve()
    anchor_cache = {} if anchor_cache is None else anchor_cache
    display_source = source.relative_to(repo).as_posix()
    text, matches = _markdown_link_matches(source.read_text(encoding="utf-8"))
    errors: list[str] = []

    for match in matches:
        raw_target = (match.group(1) or match.group(2)).strip()
        split = urlsplit(raw_target)
        repository_path = _canonical_repository_path(split)
        if repository_path is None and (split.scheme.lower() in REMOTE_SCHEMES or split.netloc):
            continue

        decoded_path = unquote(split.path)
        if repository_path is not None:
            target = repo / repository_path
        elif decoded_path.startswith("/"):
            target = repo / decoded_path.lstrip("/")
        elif decoded_path:
            target = source.parent / decoded_path
        else:
            target = source

        resolved = target.resolve()
        line = _line_number(text, match.start())
        try:
            relative = resolved.relative_to(repo).as_posix()
        except ValueError:
            errors.append(
                f"{display_source}:{line}: local link escapes the repository: {raw_target}"
            )
            continue

        if not _is_tracked_target(relative, tracked_paths):
            errors.append(
                f"{display_source}:{line}: local link target is not tracked: {raw_target}"
            )
            continue

        if split.fragment and resolved.suffix.lower() in {".md", ".markdown"}:
            anchor = unquote(split.fragment)
            anchors = anchor_cache.get(resolved)
            if anchors is None:
                anchors = markdown_anchors(resolved)
                anchor_cache[resolved] = anchors
            if anchor not in anchors:
                errors.append(
                    f"{display_source}:{line}: Markdown anchor does not exist: {raw_target}"
                )

    return errors


def check_repository(repo: Path) -> list[str]:
    """Validate every tracked ``.md`` file in a repository."""
    tracked = tracked_files(repo)
    anchor_cache: dict[Path, set[str]] = {}
    markdown = sorted(
        repo / path for path in tracked if Path(path).suffix.lower() in {".md", ".markdown"}
    )
    return [
        error
        for path in markdown
        for error in check_markdown_file(
            path,
            repo=repo,
            tracked_paths=tracked,
            anchor_cache=anchor_cache,
        )
    ]


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    errors = check_repository(repo)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        print(f"FAIL: {len(errors)} broken or unpublished local Markdown link(s)", file=sys.stderr)
        return 1
    print("OK: all tracked Markdown local links resolve to tracked content")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
