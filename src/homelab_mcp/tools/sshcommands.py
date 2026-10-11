"""Run a caller-supplied command on an allowlisted VM over SSH.

Equivalent to ``ssh <vm> '<command>' >> <log>`` but without a local shell:
ssh is started with a fixed argument list. Before the command runs, a header
line with the timestamp, VM and command is appended to the administrator-
defined log file; afterwards its stdout is appended as well.

Configuration (environment / .env):
  HOMELAB_MCP_SSH_VMS      comma-separated VM names the caller may select
  HOMELAB_MCP_SSH_LOG      file that receives the executed commands and their
                           stdout (appended, never overwritten)
"""
from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime
from typing import Any

_VMS_VAR = "HOMELAB_MCP_SSH_VMS"
_LOG_VAR = "HOMELAB_MCP_SSH_LOG"
_VM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,127}$")
_MAX_COMMAND_LENGTH = 4096
_MAX_STDERR_CHARS = 4096
_MAX_OUTPUT_CHARS = 65536
_TIMEOUT_SECONDS = 120


def load_ssh_vms() -> list[str]:
    """Return the configured VM names (invalid or duplicate entries dropped)."""
    vms: list[str] = []
    for item in os.environ.get(_VMS_VAR, "").split(","):
        name = item.strip()
        if _VM_RE.fullmatch(name) and name not in vms:
            vms.append(name)
    return vms


def ssh_log_path() -> str | None:
    """Return the configured log file path, or None if unset."""
    return os.environ.get(_LOG_VAR, "").strip() or None


def run_ssh_command(vm: str, command: str) -> dict[str, Any]:
    """Run a command on one allowlisted VM via SSH.

    vm must be one of the machine names configured by the administrator
    (see the tool description). command is executed by the remote user's
    shell. The command is appended to the administrator-defined log file
    before it runs, followed by its stdout. Returns the exit code, stdout
    (capped), and any stderr.
    """
    if not isinstance(vm, str):
        return {"error": "vm must be a string"}
    if not isinstance(command, str):
        return {"error": "command must be a string"}

    vms = load_ssh_vms()
    log_path = ssh_log_path()
    if not vms or log_path is None:
        return {
            "error": (
                f"SSH commands are not configured; set {_VMS_VAR} and {_LOG_VAR}"
            )
        }
    if vm not in vms:
        return {"error": "unknown vm", "available_vms": vms}
    if not command.strip():
        return {"error": "command must not be empty"}
    if len(command) > _MAX_COMMAND_LENGTH or "\x00" in command:
        return {
            "error": (
                f"command must be at most {_MAX_COMMAND_LENGTH} characters "
                "and cannot contain NUL"
            )
        }

    argv = ["ssh", "-o", "BatchMode=yes", "--", vm, command]
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        with open(log_path, "a", encoding="utf-8") as log:
            # Logged (and flushed) before execution so the command is
            # recorded even if ssh hangs or the server is killed.
            log.write(f"[{timestamp}] {vm}$ {command}\n")
            log.flush()
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_SECONDS,
                check=False,
            )
            log.write(proc.stdout)
            if proc.stdout and not proc.stdout.endswith("\n"):
                log.write("\n")
    except subprocess.TimeoutExpired:
        return {"error": f"ssh command exceeded {_TIMEOUT_SECONDS} seconds"}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"error": f"failed to run ssh command: {exc}"}

    result: dict[str, Any] = {
        "vm": vm,
        "returncode": proc.returncode,
        "stdout": proc.stdout[:_MAX_OUTPUT_CHARS],
        "truncated": len(proc.stdout) > _MAX_OUTPUT_CHARS,
        "log": log_path,
    }
    stderr = proc.stderr.strip()
    if stderr:
        result["stderr"] = stderr[:_MAX_STDERR_CHARS]
    return result


def tool_description() -> str:
    """Build the MCP-visible tool description with the allowed VM names."""
    vms = load_ssh_vms()
    available = ", ".join(vms) if vms else "none configured"
    return (
        "Run a command on one allowlisted VM via SSH "
        "(ssh <vm> '<command>' >> <log>). vm must be one of the configured "
        "machine names; command is executed by the remote shell. The command "
        "and its stdout are appended to the administrator-defined log file; "
        "stdout, stderr and the exit code are also returned. This tool can "
        f"modify the remote machine. Available VMs: {available}."
    )
