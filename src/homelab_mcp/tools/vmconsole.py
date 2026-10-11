"""Run a caller-supplied command on an allowlisted VM's serial console.

Uses ``virsh console <vm>`` (the local libvirt serial console). Before the
command is sent, a header line with the timestamp, VM and command is appended
to the administrator-defined log file; afterwards the console output and any
virsh stderr are appended as well.

A serial console has no exit status for the typed command and no end-of-output
marker, so output is collected until the console has been quiet for a short
while (or a total time limit is hit). The returned ``returncode`` is the exit
code of the ``virsh console`` process, not of the command typed into the VM.
The VM's console must already offer a usable shell (e.g. auto-login).

Configuration (environment / .env):
  HOMELAB_MCP_KVM_VMS      comma-separated libvirt domain names the caller may
                           select
  HOMELAB_MCP_KVM_LOG      file that receives the executed commands and their
                           output (appended, never overwritten)
"""
from __future__ import annotations

import os
import pty
import re
import select
import subprocess
import time
from datetime import datetime
from typing import Any

_VMS_VAR = "HOMELAB_MCP_KVM_VMS"
_LOG_VAR = "HOMELAB_MCP_KVM_LOG"
_VM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,127}$")
_MAX_COMMAND_LENGTH = 4096
_MAX_STDERR_CHARS = 4096
_MAX_OUTPUT_CHARS = 65536
_CONNECT_TIMEOUT_SECONDS = 10
_IDLE_SECONDS = 2.0
_TIMEOUT_SECONDS = 30
_CLOSE_WAIT_SECONDS = 3
_ESCAPE = b"\x1d"  # Ctrl-] ends `virsh console`
_CONNECTED_MARKER = b"Escape character"


def load_kvm_vms() -> list[str]:
    """Return the configured VM names (invalid or duplicate entries dropped)."""
    vms: list[str] = []
    for item in os.environ.get(_VMS_VAR, "").split(","):
        name = item.strip()
        if _VM_RE.fullmatch(name) and name not in vms:
            vms.append(name)
    return vms


def kvm_log_path() -> str | None:
    """Return the configured log file path, or None if unset."""
    return os.environ.get(_LOG_VAR, "").strip() or None


def _read_available(fd: int, wait: float) -> bytes | None:
    """Read from fd; b"" if nothing arrived within wait, None on EOF."""
    ready, _, _ = select.select([fd], [], [], wait)
    if not ready:
        return b""
    try:
        data = os.read(fd, 4096)
    except OSError:  # EIO: the child closed its side of the pty
        return None
    return data or None


def _talk_to_console(proc: subprocess.Popen, master: int, command: str) -> tuple[bytes, bool]:
    """Send command to the console; return (output, hit_total_timeout)."""
    # Wait for virsh to report the console is attached.
    banner = b""
    deadline = time.monotonic() + _CONNECT_TIMEOUT_SECONDS
    while _CONNECTED_MARKER not in banner and time.monotonic() < deadline:
        chunk = _read_available(master, 0.1)
        if chunk is None:
            return b"", False
        banner += chunk
    if _CONNECTED_MARKER not in banner:
        return b"", False

    os.write(master, command.encode("utf-8") + b"\n")

    output = b""
    start = last_data = time.monotonic()
    while True:
        now = time.monotonic()
        if now - start >= _TIMEOUT_SECONDS:
            return output, True
        if now - last_data >= _IDLE_SECONDS:
            return output, False
        chunk = _read_available(master, 0.1)
        if chunk is None:
            return output, False
        if chunk:
            output += chunk
            last_data = time.monotonic()


def _run_console(vm: str, command: str) -> tuple[int, str, str, bool]:
    """Run one command; return (virsh returncode, output, virsh stderr, timed_out)."""
    master, slave = pty.openpty()
    try:
        proc = subprocess.Popen(
            ["virsh", "console", vm],
            stdin=slave,
            stdout=slave,
            stderr=subprocess.PIPE,
            close_fds=True,
        )
    except OSError:
        os.close(master)
        raise
    finally:
        os.close(slave)
    try:
        try:
            output, timed_out = _talk_to_console(proc, master, command)
        finally:
            try:
                os.write(master, _ESCAPE)
            except OSError:
                pass
            try:
                proc.wait(timeout=_CLOSE_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        stderr = proc.stderr.read().decode("utf-8", errors="replace")
    finally:
        os.close(master)
        proc.stderr.close()
    text = output.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    return proc.returncode, text, stderr, timed_out


def run_vm_console_command(vm: str, command: str) -> dict[str, Any]:
    """Run a command on one allowlisted VM's serial console (virsh console).

    vm must be one of the libvirt domain names configured by the administrator
    (see the tool description). command is typed into the VM's console shell.
    The command is appended to the administrator-defined log file before it
    is sent, followed by the console output and stderr. Output ends once the
    console has been quiet for a moment. Returns the output (capped), stderr
    and the exit code of `virsh console` (not of the typed command).
    """
    if not isinstance(vm, str):
        return {"error": "vm must be a string"}
    if not isinstance(command, str):
        return {"error": "command must be a string"}

    vms = load_kvm_vms()
    log_path = kvm_log_path()
    if not vms or log_path is None:
        return {
            "error": (
                f"VM console commands are not configured; set {_VMS_VAR} and {_LOG_VAR}"
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
    if "\n" in command or "\r" in command:
        return {"error": "command must be a single line"}

    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        with open(log_path, "a", encoding="utf-8") as log:
            # Logged (and flushed) before execution so the command is
            # recorded even if virsh hangs or the server is killed.
            log.write(f"[{timestamp}] {vm}$ {command}\n")
            log.flush()
            returncode, output, stderr, timed_out = _run_console(vm, command)
            for stream in (output, stderr):
                log.write(stream)
                if stream and not stream.endswith("\n"):
                    log.write("\n")
    except (OSError, subprocess.SubprocessError) as exc:
        return {"error": f"failed to run virsh console: {exc}"}

    result: dict[str, Any] = {
        "vm": vm,
        "returncode": returncode,
        "stdout": output[:_MAX_OUTPUT_CHARS],
        "truncated": len(output) > _MAX_OUTPUT_CHARS,
        "timed_out": timed_out,
        "log": log_path,
    }
    stderr = stderr.strip()
    if stderr:
        result["stderr"] = stderr[:_MAX_STDERR_CHARS]
    return result


def tool_description() -> str:
    """Build the MCP-visible tool description with the allowed VM names."""
    vms = load_kvm_vms()
    available = ", ".join(vms) if vms else "none configured"
    return (
        "Run a single-line command on one allowlisted VM via its local "
        "serial console (virsh console). vm must be one of the configured "
        "libvirt domain names; command is typed into the console shell. The "
        "command and the console output are appended to the administrator-"
        "defined log file; output, stderr and the exit code of `virsh "
        "console` (not of the typed command) are also returned. Output ends "
        "when the console has been quiet for a moment. This tool can modify "
        f"the VM. Available VMs: {available}."
    )
