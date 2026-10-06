"""Execute administrator-defined commands with output-only filtering.

Commands are loaded from HOMELAB_MCP_SHELL_COMMAND_<ALIAS> environment
variables. MCP callers can select an alias and filter its output, but cannot
supply, append, replace, or interpolate command text or command arguments.
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import Any

_COMMAND_PREFIX = "HOMELAB_MCP_SHELL_COMMAND_"
_ALIAS_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MATCH_RE = re.compile(r"^[A-Za-z0-9 ._:/+@()\[\]-]{1,100}$")
_TIMEOUT_SECONDS = 30
_MAX_OUTPUT_LINES = 500


def load_shell_commands() -> dict[str, str]:
    """Load configured commands keyed by normalized MCP-visible alias."""
    commands: dict[str, str] = {}
    for variable_name, command in os.environ.items():
        if not variable_name.startswith(_COMMAND_PREFIX):
            continue
        alias = variable_name[len(_COMMAND_PREFIX):].strip().lower()
        command = command.strip()
        if not _ALIAS_RE.fullmatch(alias) or not command:
            continue
        commands[alias] = command
    return dict(sorted(commands.items()))


def available_shell_command_aliases() -> list[str]:
    """Return configured aliases without exposing their command text."""
    return list(load_shell_commands())


def list_shell_commands() -> dict[str, Any]:
    """List shell-command aliases configured by the server administrator.

    The underlying command text is intentionally not returned.
    """
    aliases = available_shell_command_aliases()
    return {"commands": aliases, "count": len(aliases)}


def run_shell_command(alias: str, match: str = "") -> dict[str, Any]:
    """Run one configured command and optionally filter its output.

    Available aliases are advertised in the MCP tool description and by
    list_shell_commands(). The caller cannot provide command text or command
    arguments. match is an optional literal, case-insensitive output filter.
    """
    if not isinstance(alias, str):
        return {"error": "alias must be a string"}
    normalized_alias = alias.strip().lower()
    if not _ALIAS_RE.fullmatch(normalized_alias):
        return {"error": "invalid shell-command alias"}

    if not isinstance(match, str):
        return {"error": "match must be a string"}
    if match and not _MATCH_RE.fullmatch(match):
        return {
            "error": (
                "match must contain 1 to 100 allowlisted characters and "
                "cannot contain shell control characters"
            )
        }

    commands = load_shell_commands()
    command = commands.get(normalized_alias)
    if command is None:
        return {
            "error": "unknown shell-command alias",
            "available_commands": list(commands),
        }

    try:
        proc = subprocess.run(
            ["/bin/sh", "-c", command],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"error": f"shell command exceeded {_TIMEOUT_SECONDS} seconds"}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"error": f"failed to execute configured shell command: {exc}"}

    stdout_lines = proc.stdout.splitlines()
    if match:
        needle = match.casefold()
        stdout_lines = [line for line in stdout_lines if needle in line.casefold()]

    total_matches = len(stdout_lines)
    returned_lines = stdout_lines[:_MAX_OUTPUT_LINES]
    result: dict[str, Any] = {
        "alias": normalized_alias,
        "match": match,
        "returncode": proc.returncode,
        "lines": returned_lines,
        "count": len(returned_lines),
        "total_matches": total_matches,
        "truncated": total_matches > len(returned_lines),
    }
    if proc.stderr.strip():
        result["stderr"] = proc.stderr.strip()
    return result


def tool_description() -> str:
    """Build the MCP-visible tool description with configured aliases."""
    aliases = available_shell_command_aliases()
    available = ", ".join(aliases) if aliases else "none configured"
    return (
        "Run one administrator-defined shell command by alias. The caller can "
        "only select an alias and optionally apply a literal output filter; "
        "command text and arguments cannot be supplied or modified. "
        f"Available aliases: {available}."
    )
