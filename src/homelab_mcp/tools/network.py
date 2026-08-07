"""Read-only journal and network inspection tools.

recent_journal_errors() shells out to journalctl with a fixed argument
list and strictly validated inputs (never shell=True, never string
interpolation). network_connections() uses psutil, not subprocess.
"""

from __future__ import annotations

import re
import socket
import subprocess
from typing import Any

import psutil

# e.g. "1h", "30m", "2d" -- a plain integer followed by a single unit char.
_SINCE_RE = re.compile(r"^\d{1,4}[hmd]$")

# journalctl's valid syslog priority names (also accepts numeric 0-7, but
# we restrict to names for clarity in tool calls).
_VALID_PRIORITIES = {
    "emerg",
    "alert",
    "crit",
    "err",
    "warning",
    "notice",
    "info",
    "debug",
}

_SUBPROCESS_TIMEOUT_SECONDS = 15

_UNIT_WORDS = {"h": "hours", "m": "minutes", "d": "days"}


def _since_to_journalctl_arg(since: str) -> str:
    """Convert a validated "<N><h|m|d>" value into journalctl's
    "N unit ago" relative time syntax (e.g. "2h" -> "2 hours ago").
    """
    amount, unit = since[:-1], since[-1]
    return f"{amount} {_UNIT_WORDS[unit]} ago"


def recent_journal_errors(since: str = "1h", priority: str = "err") -> dict[str, Any]:
    """Get recent systemd journal entries at or above a given priority.

    `since` is a relative time window like "1h" (1 hour), "30m" (30
    minutes), or "2d" (2 days) -- default "1h". `priority` is a syslog
    priority level name: emerg, alert, crit, err, warning, notice, info,
    or debug -- default "err" (errors and worse). Use this to quickly find
    what's been going wrong recently across the whole system, before
    narrowing down to a specific service's logs.
    """
    if not _SINCE_RE.match(since):
        return {
            "error": (
                f"invalid since={since!r}: must match {_SINCE_RE.pattern} "
                "(e.g. '1h', '30m', '2d')"
            )
        }

    if priority not in _VALID_PRIORITIES:
        return {
            "error": f"invalid priority={priority!r}: must be one of {sorted(_VALID_PRIORITIES)}"
        }

    try:
        proc = subprocess.run(
            [
                "journalctl",
                f"--since={_since_to_journalctl_arg(since)}",
                f"--priority={priority}",
                "--no-pager",
                "--output=short-iso",
            ],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"error": f"failed to run journalctl: {exc}"}

    if proc.returncode != 0:
        return {"error": f"journalctl exited {proc.returncode}: {proc.stderr.strip()}"}

    entries = [line for line in proc.stdout.splitlines() if line.strip()]
    return {"since": since, "priority": priority, "entries": entries, "count": len(entries)}


def network_connections() -> dict[str, Any]:
    """List listening TCP and UDP sockets on this host.

    Returns local address, port, protocol, and owning process name (where
    permitted by OS privileges) for every socket in a listening state. Use
    this to check what services are actually exposed on the network, e.g.
    to confirm a port is bound or to spot something unexpected listening.
    """
    try:
        conns = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, PermissionError) as exc:
        return {"error": f"insufficient permissions to list connections: {exc}"}

    listening = []
    for conn in conns:
        if conn.status not in ("LISTEN", "NONE"):
            continue
        # UDP sockets report status "NONE"; treat those with a laddr as
        # effectively "listening" for our purposes, skip the rest.
        if conn.status == "NONE" and conn.type != socket.SOCK_DGRAM:
            continue
        if not conn.laddr:
            continue

        proc_name = None
        if conn.pid:
            try:
                proc_name = psutil.Process(conn.pid).name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                proc_name = None

        protocol = "udp" if conn.type == socket.SOCK_DGRAM else "tcp"
        listening.append(
            {
                "protocol": protocol,
                "local_address": conn.laddr.ip,
                "local_port": conn.laddr.port,
                "pid": conn.pid,
                "process_name": proc_name,
            }
        )

    return {"listening_sockets": listening, "count": len(listening)}
