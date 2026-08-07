"""Read-only Docker inspection tools: list containers and tail their logs.

Uses the docker-py SDK exclusively (talks to the Docker socket/API
directly) -- never shells out to the `docker` CLI, so there is no command
injection surface here.
"""

from __future__ import annotations

from typing import Any

import docker
from docker.errors import DockerException, NotFound


def _client() -> docker.DockerClient:
    return docker.from_env()


def _format_ports(ports: dict[str, Any]) -> list[str]:
    formatted = []
    for container_port, bindings in (ports or {}).items():
        if not bindings:
            formatted.append(f"{container_port} (unpublished)")
            continue
        for binding in bindings:
            host_ip = binding.get("HostIp") or "0.0.0.0"
            host_port = binding.get("HostPort")
            formatted.append(f"{host_ip}:{host_port} -> {container_port}")
    return formatted


def list_containers() -> list[dict[str, Any]]:
    """List all Docker containers (running and stopped) with basic info.

    Returns each container's name, image, status (running/exited/paused/
    etc.), and published port mappings. Use this first to see what's
    deployed and its current state before pulling logs for a specific
    container with container_logs().
    """
    try:
        client = _client()
        containers = client.containers.list(all=True)
    except DockerException as exc:
        return [{"error": f"failed to connect to Docker: {exc}"}]

    result = []
    for c in containers:
        image_tags = c.image.tags
        image_name = image_tags[0] if image_tags else c.image.short_id
        ports = c.attrs.get("NetworkSettings", {}).get("Ports", {})
        result.append(
            {
                "name": c.name,
                "image": image_name,
                "status": c.status,
                "ports": _format_ports(ports),
            }
        )
    return result


def container_logs(name: str, lines: int = 100) -> dict[str, Any]:
    """Get the most recent log lines from a specific Docker container.

    `name` must match an existing container's name exactly (case-sensitive)
    -- call list_containers() first if unsure what's available. `lines`
    controls how many trailing log lines to fetch (default 100, capped at
    2000). Use this to debug why a service is crashing or misbehaving.
    """
    lines = max(1, min(int(lines), 2000))

    try:
        client = _client()
    except DockerException as exc:
        return {"error": f"failed to connect to Docker: {exc}"}

    # Validate the name against the real container list before touching
    # the Docker API with it -- never trust caller-supplied identifiers.
    valid_names = {c.name for c in client.containers.list(all=True)}
    if name not in valid_names:
        return {"error": f"no container named {name!r}. Call list_containers() to see valid names."}

    try:
        container = client.containers.get(name)
        raw_logs = container.logs(tail=lines, timestamps=True)
    except NotFound:
        return {"error": f"container {name!r} disappeared before logs could be fetched"}
    except DockerException as exc:
        return {"error": f"failed to fetch logs for {name!r}: {exc}"}

    text = raw_logs.decode("utf-8", errors="replace")
    return {"name": name, "lines_requested": lines, "logs": text}
