"""Read-only operating-system and hardware inspection tools.

All subprocess calls use fixed argument lists and never use shell=True.
Filtering is performed in Python, so caller input is never interpreted by a
shell or regular-expression engine.
"""
from __future__ import annotations

import re
import subprocess
from typing import Any

_MATCH_RE = re.compile(r"^[A-Za-z0-9 ._:/+@()-]{1,100}$")
_SUBPROCESS_TIMEOUT_SECONDS = 30
_MAX_DPKG_LINES = 500


def _validate_match(match: str, *, required: bool) -> str | None:
    if not isinstance(match, str):
        return "match must be a string"
    if not match:
        return "match is required" if required else None
    if not _MATCH_RE.fullmatch(match):
        return (
            "match must contain 1 to 100 characters from this allowlist: "
            "letters, digits, spaces, dot, underscore, colon, slash, plus, "
            "at sign, parentheses, and dash"
        )
    return None


def _validate_context_lines(value: int, name: str) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return f"{name} must be an integer between 0 and 20"
    if not 0 <= value <= 20:
        return f"{name} must be an integer between 0 and 20"
    return None


def uname_info() -> dict[str, Any]:
    """Return the complete kernel and system identification from uname -a."""
    try:
        proc = subprocess.run(
            ["uname", "-a"],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"error": f"failed to run uname: {exc}"}

    if proc.returncode != 0:
        return {"error": f"uname exited {proc.returncode}: {proc.stderr.strip()}"}

    return {"returncode": proc.returncode, "output": proc.stdout.strip()}


def dpkg_packages(match: str = "") -> dict[str, Any]:
    """List installed-package records, optionally filtered by a literal match.

    Filtering is case-insensitive and literal. An empty match returns the first
    500 non-empty lines and reports whether the result was truncated.
    """
    error = _validate_match(match, required=False)
    if error:
        return {"error": error}

    try:
        proc = subprocess.run(
            ["dpkg", "-l"],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"error": f"failed to run dpkg: {exc}"}

    if proc.returncode != 0:
        return {"error": f"dpkg exited {proc.returncode}: {proc.stderr.strip()}"}

    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if match:
        needle = match.casefold()
        lines = [line for line in lines if needle in line.casefold()]

    total_matches = len(lines)
    returned = lines[:_MAX_DPKG_LINES]
    return {
        "match": match,
        "lines": returned,
        "count": len(returned),
        "total_matches": total_matches,
        "truncated": total_matches > len(returned),
    }


def dmidecode_search(
    match: str,
    after_lines: int = 0,
    before_lines: int = 0,
) -> dict[str, Any]:
    """Search dmidecode output using a literal, case-insensitive string.

    match is required. after_lines and before_lines must each be integers from
    0 through 20. dmidecode may require root or equivalent privileges.
    """
    error = _validate_match(match, required=True)
    if error:
        return {"error": error}
    error = _validate_context_lines(after_lines, "after_lines")
    if error:
        return {"error": error}
    error = _validate_context_lines(before_lines, "before_lines")
    if error:
        return {"error": error}

    try:
        proc = subprocess.run(
            ["dmidecode"],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return {"error": "dmidecode is not installed or not available in PATH"}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"error": f"failed to run dmidecode: {exc}"}

    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        return {
            "error": (
                f"dmidecode exited {proc.returncode}: {detail}. "
                "The MCP process may require root or equivalent privileges."
            )
        }

    lines = proc.stdout.splitlines()
    needle = match.casefold()
    matching_indexes = [
        index for index, line in enumerate(lines) if needle in line.casefold()
    ]

    selected_indexes: set[int] = set()
    for index in matching_indexes:
        start = max(0, index - before_lines)
        stop = min(len(lines), index + after_lines + 1)
        selected_indexes.update(range(start, stop))

    selected_lines = [lines[index] for index in sorted(selected_indexes)]
    return {
        "match": match,
        "before_lines": before_lines,
        "after_lines": after_lines,
        "match_count": len(matching_indexes),
        "lines": selected_lines,
        "count": len(selected_lines),
    }
