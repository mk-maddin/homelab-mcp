"""Read-only systemd inspection tools: list units and show unit status.

All subprocess calls use a fixed argument list (never shell=True, never
string interpolation into a shell command). Any caller-supplied value is
validated against a strict allowlist pattern before it is placed into the
argument list.
"""

from __future__ import annotations

import re
import subprocess
from typing import Any

# Matches systemd unit names: alphanumeric, dash, underscore, dot, '@' for
# templated units, and must end in ".service".
_UNIT_NAME_RE = re.compile(r"^[A-Za-z0-9_.@-]+\.service$")

_SUBPROCESS_TIMEOUT_SECONDS = 15


def list_services() -> dict[str, Any]:
    """List all systemd service units and their load/active/sub state.

    Returns every known service unit (running or not) with its three
    systemd state fields: load state (e.g. loaded), active state (e.g.
    active/failed/inactive), and sub state (e.g. running/dead/exited). Use
    this to get an overview of what's installed and spot failed services
    before drilling into one with service_status().
    """
    try:
        proc = subprocess.run(
            ["systemctl", "list-units", "--type=service", "--no-pager", "--plain", "--all"],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"error": f"failed to run systemctl: {exc}"}

    if proc.returncode != 0:
        return {"error": f"systemctl exited {proc.returncode}: {proc.stderr.strip()}"}

    units = []
    lines = proc.stdout.splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith(("UNIT", "LOAD", "●")):
            continue
        # Columns: UNIT LOAD ACTIVE SUB DESCRIPTION...
        parts = line.split(None, 4)
        if len(parts) < 4 or not parts[0].endswith(".service"):
            continue
        unit, load, active, sub = parts[0], parts[1], parts[2], parts[3]
        description = parts[4] if len(parts) > 4 else ""
        units.append(
            {
                "unit": unit,
                "load": load,
                "active": active,
                "sub": sub,
                "description": description,
            }
        )

    return {"units": units, "count": len(units)}


def service_status(unit: str) -> dict[str, Any]:
    """Get detailed systemctl status output for a single systemd service unit.

    `unit` must be a valid systemd service name ending in ".service" (e.g.
    "sshd.service", "docker.service") -- call list_services() first if
    you're not sure of the exact unit name. Returns the raw `systemctl
    status` text, which includes recent log lines and process info.
    """
    if not _UNIT_NAME_RE.match(unit):
        return {
            "error": (
                f"invalid unit name {unit!r}: must match {_UNIT_NAME_RE.pattern} "
                "(alphanumeric, dash, underscore, dot, '@' only, ending in .service)"
            )
        }

    try:
        proc = subprocess.run(
            ["systemctl", "status", "--no-pager", "--full", unit],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"error": f"failed to run systemctl: {exc}"}

    # systemctl status returns non-zero for inactive/failed units too --
    # that's not a tool failure, the output is still meaningful.
    return {"unit": unit, "returncode": proc.returncode, "status": proc.stdout.strip()}
