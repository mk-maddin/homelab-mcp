"""Read-only system health tools: CPU/memory/uptime and disk usage."""

from __future__ import annotations

import shutil
import time
from typing import Any

import psutil


def system_status() -> dict[str, Any]:
    """Get overall system health: uptime, load average, memory, and CPU usage.

    Call this for a quick "is the box healthy" check -- current uptime,
    1/5/15 minute load averages, memory used vs. total, logical CPU count,
    and current CPU utilization percentage. Use this before drilling into
    specific containers or services.
    """
    boot_time = psutil.boot_time()
    uptime_seconds = time.time() - boot_time

    load1, load5, load15 = psutil.getloadavg()

    mem = psutil.virtual_memory()

    return {
        "uptime_seconds": round(uptime_seconds),
        "load_average": {"1m": load1, "5m": load5, "15m": load15},
        "memory": {
            "total_bytes": mem.total,
            "used_bytes": mem.used,
            "available_bytes": mem.available,
            "percent_used": mem.percent,
        },
        "cpu": {
            "logical_count": psutil.cpu_count(logical=True),
            "physical_count": psutil.cpu_count(logical=False),
            "percent_used": psutil.cpu_percent(interval=0.5),
        },
    }


def disk_usage(path: str = "/") -> dict[str, Any]:
    """Get total/used/free disk space for a given mount path.

    Defaults to the root filesystem ("/") if no path is given. Use this to
    check whether a disk or mount point is close to full. Pass a specific
    path (e.g. "/mnt/storage", "/home") to check a particular filesystem or
    mount.
    """
    usage = shutil.disk_usage(path)
    percent = round((usage.used / usage.total) * 100, 2) if usage.total else 0.0

    return {
        "path": path,
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "percent_used": percent,
    }
