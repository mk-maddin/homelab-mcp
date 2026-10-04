"""Read-only filesystem inspection tools with path exclusions."""
from __future__ import annotations

import csv
import logging
import os
import stat
from pathlib import Path
from typing import Any

logger = logging.getLogger("homelab_mcp")

_MAX_READ_BYTES = 1_048_576
_MAX_DIRECTORY_ENTRIES = 500

_DEFAULT_DENIED_FILES = frozenset({
    Path("/etc/passwd"),
    Path("/etc/shadow"),
    Path("/etc/shadow-"),
    Path("/etc/gshadow"),
    Path("/etc/gshadow-"),
    Path("/etc/sudoers"),
    Path("/etc/sudo.conf"),
    Path("/etc/crypttab"),
})

_DEFAULT_DENIED_FOLDERS = (
    Path("/etc/sudoers.d"),
    Path("/etc/ssh"),
    Path("/etc/security"),
    Path("/opt/homelab-mcp"),
    Path("/root"),
    Path("/home"),
    Path("/proc"),
    Path("/sys"),
    Path("/dev"),
    Path("/run"),
)


def _parse_denied_paths(variable_name: str) -> tuple[Path, ...]:
    """Parse quoted or unquoted comma-separated absolute paths."""
    raw_value = os.environ.get(variable_name, "").strip()
    if not raw_value:
        return ()
    try:
        entries = next(csv.reader([raw_value], skipinitialspace=True))
    except (csv.Error, StopIteration):
        return ()

    paths: list[Path] = []
    for entry in entries:
        value = entry.strip()
        if not value:
            continue
        candidate = Path(value)
        if not candidate.is_absolute():
            continue
        try:
            normalized = candidate.resolve(strict=False)
        except (OSError, RuntimeError):
            continue
        if normalized not in paths:
            paths.append(normalized)
    return tuple(paths)


_EXTRA_DENIED_FILES = _parse_denied_paths(
    "HOMELAB_MCP_DENIED_FILES"
)
_EXTRA_DENIED_FOLDERS = _parse_denied_paths(
    "HOMELAB_MCP_DENIED_FOLDERS"
)

logger.info(
    "Denied paths: built-in files=%d, built-in folders=%d, env files=%d, env folders=%d",
    len(_DEFAULT_DENIED_FILES),
    len(_DEFAULT_DENIED_FOLDERS),
    len(_EXTRA_DENIED_FILES),
    len(_EXTRA_DENIED_FOLDERS),
)


def _denied_files() -> frozenset[Path]:
    return _DEFAULT_DENIED_FILES.union(_EXTRA_DENIED_FILES)


def _denied_folders() -> tuple[Path, ...]:
    return tuple(dict.fromkeys((*_DEFAULT_DENIED_FOLDERS, *_EXTRA_DENIED_FOLDERS)))


def _resolve_requested_path(raw_path: str) -> tuple[Path | None, str | None]:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None, "path must be a non-empty absolute path"
    requested = Path(raw_path)
    if not requested.is_absolute():
        return None, "path must be absolute"
    try:
        resolved = requested.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        return None, f"cannot resolve path: {exc}"
    if resolved in _denied_files():
        return None, "access to this file is denied by mcp server"
    for denied_folder in _denied_folders():
        if resolved == denied_folder or denied_folder in resolved.parents:
            return None, "access to this directory tree is denied  by mcp server"
    return resolved, None


def read_file(path: str, max_bytes: int = _MAX_READ_BYTES) -> dict[str, Any]:
    """Read a permitted regular text file without modifying it."""
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
        "path": str(resolved), "size_bytes": info.st_size,
        "bytes_returned": len(data), "truncated": truncated,
        "content": data.decode("utf-8", errors="replace"),
    }


def list_directory(path: str, max_entries: int = 200) -> dict[str, Any]:
    """List one permitted directory level without reading file contents."""
    resolved, error = _resolve_requested_path(path)
    if error:
        return {"error": error, "path": path}
    assert resolved is not None
    if not resolved.is_dir():
        return {"error": "path is not a directory", "path": str(resolved)}
    limit = max(1, min(int(max_entries), _MAX_DIRECTORY_ENTRIES))
    entries: list[dict[str, Any]] = []
    truncated = False
    try:
        with os.scandir(resolved) as iterator:
            for entry in iterator:
                if len(entries) >= limit:
                    truncated = True
                    break
                try:
                    entry_type = (
                        "symlink" if entry.is_symlink() else
                        "directory" if entry.is_dir(follow_symlinks=False) else
                        "file" if entry.is_file(follow_symlinks=False) else "other"
                    )
                except OSError:
                    entry_type = "unknown"
                entries.append({"name": entry.name, "type": entry_type})
    except (OSError, PermissionError) as exc:
        return {"error": f"cannot list directory: {exc}", "path": str(resolved)}
    entries.sort(key=lambda item: item["name"].casefold())
    return {
        "path": str(resolved), "entries": entries,
        "count": len(entries), "truncated": truncated,
    }
