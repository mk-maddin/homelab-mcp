"""Read-only filesystem inspection tools with explicit path exclusions."""
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

_MAX_READ_BYTES = 1_048_576
_MAX_DIRECTORY_ENTRIES = 500

# Exact files that must never be exposed.
_DENIED_FILES = {
    Path("/etc/passwd"),
    Path("/etc/shadow"),
    Path("/etc/gshadow"),
    Path("/etc/sudoers"),
    Path("/etc/ssh/sshd_config"),
}

# Entire directory trees that must never be exposed.
_DENIED_DIRECTORIES = (
    Path("/etc/sudoers.d"),
    Path("/etc/ssh/ssh_host_keys"),
    Path("/root"),
    Path("/home"),
    Path("/proc"),
    Path("/sys"),
    Path("/dev"),
    Path("/run"),
)


def _resolve_requested_path(raw_path: str) -> tuple[Path | None, str | None]:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None, "path must be a non-empty absolute path"

    requested = Path(raw_path)
    if not requested.is_absolute():
        return None, "path must be absolute"

    try:
        # strict=True also rejects missing paths and resolves symlink targets.
        resolved = requested.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        return None, f"cannot resolve path: {exc}"

    if resolved in _DENIED_FILES:
        return None, "access to this file is denied"

    for denied_dir in _DENIED_DIRECTORIES:
        if resolved == denied_dir or denied_dir in resolved.parents:
            return None, "access to this directory tree is denied"

    return resolved, None


def read_file(path: str, max_bytes: int = _MAX_READ_BYTES) -> dict[str, Any]:
    """Read a regular text file without modifying it.

    The path must be absolute. Sensitive files and directory trees are
    blocked, symlink targets are resolved before policy checks, and reads are
    capped at 1 MiB. Binary files are rejected.
    """
    resolved, error = _resolve_requested_path(path)
    if error:
        return {"error": error, "path": path}
    assert resolved is not None

    try:
        info = resolved.stat()
    except OSError as exc:
        return {"error": f"cannot stat file: {exc}", "path": str(resolved)}

    if not stat.S_ISREG(info.st_mode):
        return {"error": "path is not a regular file", "path": str(resolved)}

    requested_limit = max(1, min(int(max_bytes), _MAX_READ_BYTES))
    try:
        with resolved.open("rb") as handle:
            data = handle.read(requested_limit + 1)
    except (OSError, PermissionError) as exc:
        return {"error": f"cannot read file: {exc}", "path": str(resolved)}

    truncated = len(data) > requested_limit
    data = data[:requested_limit]
    if b"\x00" in data:
        return {"error": "binary files are not supported", "path": str(resolved)}

    return {
        "path": str(resolved),
        "size_bytes": info.st_size,
        "bytes_returned": len(data),
        "truncated": truncated,
        "content": data.decode("utf-8", errors="replace"),
    }


def list_directory(path: str, max_entries: int = 200) -> dict[str, Any]:
    """List one directory level without reading file contents.

    The path must be absolute. Sensitive directory trees are blocked and the
    result is capped at 500 entries. Symlinks are identified but not followed
    while enumerating entries.
    """
    resolved, error = _resolve_requested_path(path)
    if error:
        return {"error": error, "path": path}
    assert resolved is not None

    if not resolved.is_dir():
        return {"error": "path is not a directory", "path": str(resolved)}

    limit = max(1, min(int(max_entries), _MAX_DIRECTORY_ENTRIES))
    entries: list[dict[str, Any]] = []
    try:
        with os.scandir(resolved) as iterator:
            for entry in iterator:
                if len(entries) >= limit:
                    break
                try:
                    entries.append(
                        {
                            "name": entry.name,
                            "type": (
                                "symlink"
                                if entry.is_symlink()
                                else "directory"
                                if entry.is_dir(follow_symlinks=False)
                                else "file"
                                if entry.is_file(follow_symlinks=False)
                                else "other"
                            ),
                        }
                    )
                except OSError:
                    entries.append({"name": entry.name, "type": "unknown"})
    except (OSError, PermissionError) as exc:
        return {"error": f"cannot list directory: {exc}", "path": str(resolved)}

    entries.sort(key=lambda item: item["name"].casefold())
    return {
        "path": str(resolved),
        "entries": entries,
        "count": len(entries),
        "truncated": len(entries) >= limit,
    }
