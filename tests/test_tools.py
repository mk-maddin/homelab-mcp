"""Unit tests for homelab_mcp tools.

All external dependencies (psutil, docker-py, subprocess) are mocked so
these tests never touch the real system, real Docker daemon, or spawn
real subprocesses.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from homelab_mcp.tools import containers, network, services, system

# ---------------------------------------------------------------------------
# system.py
# ---------------------------------------------------------------------------


def test_system_status_returns_expected_shape():
    with (
        patch.object(system.psutil, "boot_time", return_value=1_000_000.0),
        patch.object(system.time, "time", return_value=1_000_100.0),
        patch.object(system.psutil, "getloadavg", return_value=(0.1, 0.2, 0.3)),
        patch.object(
            system.psutil,
            "virtual_memory",
            return_value=SimpleNamespace(total=16_000_000_000, used=8_000_000_000, available=8_000_000_000, percent=50.0),
        ),
        patch.object(system.psutil, "cpu_count", side_effect=lambda logical=True: 8 if logical else 4),
        patch.object(system.psutil, "cpu_percent", return_value=12.5),
    ):
        result = system.system_status()

    assert result["uptime_seconds"] == 100
    assert result["load_average"] == {"1m": 0.1, "5m": 0.2, "15m": 0.3}
    assert result["memory"]["total_bytes"] == 16_000_000_000
    assert result["memory"]["percent_used"] == 50.0
    assert result["cpu"]["logical_count"] == 8
    assert result["cpu"]["physical_count"] == 4
    assert result["cpu"]["percent_used"] == 12.5


def test_disk_usage_computes_percent():
    fake_usage = SimpleNamespace(total=1000, used=250, free=750)
    with patch.object(system.shutil, "disk_usage", return_value=fake_usage) as mock_du:
        result = system.disk_usage("/data")

    mock_du.assert_called_once_with("/data")
    assert result["path"] == "/data"
    assert result["total_bytes"] == 1000
    assert result["used_bytes"] == 250
    assert result["free_bytes"] == 750
    assert result["percent_used"] == 25.0


def test_disk_usage_defaults_to_root():
    fake_usage = SimpleNamespace(total=100, used=0, free=100)
    with patch.object(system.shutil, "disk_usage", return_value=fake_usage) as mock_du:
        system.disk_usage()
    mock_du.assert_called_once_with("/")


# ---------------------------------------------------------------------------
# containers.py
# ---------------------------------------------------------------------------


def _make_fake_container(name, image_tag, status, ports):
    return SimpleNamespace(
        name=name,
        status=status,
        image=SimpleNamespace(tags=[image_tag] if image_tag else [], short_id="sha256:abc123"),
        attrs={"NetworkSettings": {"Ports": ports}},
    )


def test_list_containers_formats_ports_and_status():
    fake_container = _make_fake_container(
        "grafana",
        "grafana/grafana:latest",
        "running",
        {"3000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "3000"}]},
    )
    fake_client = MagicMock()
    fake_client.containers.list.return_value = [fake_container]

    with patch.object(containers, "_client", return_value=fake_client):
        result = containers.list_containers()

    assert result == [
        {
            "name": "grafana",
            "image": "grafana/grafana:latest",
            "status": "running",
            "ports": ["0.0.0.0:3000 -> 3000/tcp"],
        }
    ]


def test_list_containers_handles_unpublished_ports_and_missing_tags():
    fake_container = _make_fake_container("worker", None, "exited", {"8080/tcp": None})
    fake_client = MagicMock()
    fake_client.containers.list.return_value = [fake_container]

    with patch.object(containers, "_client", return_value=fake_client):
        result = containers.list_containers()

    assert result[0]["image"] == "sha256:abc123"
    assert result[0]["ports"] == ["8080/tcp (unpublished)"]


def test_list_containers_docker_unavailable():
    with patch.object(containers, "_client", side_effect=containers.DockerException("no socket")):
        result = containers.list_containers()
    assert "error" in result[0]


def test_container_logs_rejects_unknown_name_without_calling_get():
    fake_client = MagicMock()
    fake_client.containers.list.return_value = [SimpleNamespace(name="known-container")]

    with patch.object(containers, "_client", return_value=fake_client):
        result = containers.container_logs("../../etc/passwd")

    assert "error" in result
    fake_client.containers.get.assert_not_called()


def test_container_logs_returns_decoded_tail():
    fake_client = MagicMock()
    fake_client.containers.list.return_value = [SimpleNamespace(name="app")]
    fake_container = MagicMock()
    fake_container.logs.return_value = b"line1\nline2\n"
    fake_client.containers.get.return_value = fake_container

    with patch.object(containers, "_client", return_value=fake_client):
        result = containers.container_logs("app", lines=50)

    fake_container.logs.assert_called_once_with(tail=50, timestamps=True)
    assert result["logs"] == "line1\nline2\n"
    assert result["name"] == "app"


def test_container_logs_clamps_line_count():
    fake_client = MagicMock()
    fake_client.containers.list.return_value = [SimpleNamespace(name="app")]
    fake_container = MagicMock()
    fake_container.logs.return_value = b""
    fake_client.containers.get.return_value = fake_container

    with patch.object(containers, "_client", return_value=fake_client):
        containers.container_logs("app", lines=999999)

    fake_container.logs.assert_called_once_with(tail=2000, timestamps=True)


# ---------------------------------------------------------------------------
# services.py
# ---------------------------------------------------------------------------


_LIST_UNITS_OUTPUT = """\
UNIT                     LOAD   ACTIVE SUB     DESCRIPTION
docker.service           loaded active running Docker Application Container Engine
sshd.service             loaded active running OpenSSH server daemon
failed.service           loaded failed failed  A failed unit

3 loaded units listed.
"""


def test_list_services_parses_output():
    fake_proc = SimpleNamespace(returncode=0, stdout=_LIST_UNITS_OUTPUT, stderr="")
    with patch.object(services.subprocess, "run", return_value=fake_proc) as mock_run:
        result = services.list_services()

    called_args = mock_run.call_args[0][0]
    assert called_args[0] == "systemctl"
    assert "shell" not in mock_run.call_args.kwargs
    assert result["count"] == 3
    assert result["units"][0] == {
        "unit": "docker.service",
        "load": "loaded",
        "active": "active",
        "sub": "running",
        "description": "Docker Application Container Engine",
    }


def test_list_services_reports_subprocess_error():
    fake_proc = SimpleNamespace(returncode=1, stdout="", stderr="permission denied")
    with patch.object(services.subprocess, "run", return_value=fake_proc):
        result = services.list_services()
    assert "error" in result


def test_service_status_rejects_invalid_unit_names():
    for bad in ["sshd; rm -rf /", "../../etc/passwd", "sshd", "sshd.timer", "$(whoami).service"]:
        result = services.service_status(bad)
        assert "error" in result, bad


@patch.object(services.subprocess, "run")
def test_service_status_never_uses_shell_true(mock_run):
    mock_run.return_value = SimpleNamespace(returncode=0, stdout="status output", stderr="")
    result = services.service_status("sshd.service")

    args, kwargs = mock_run.call_args
    assert args[0] == ["systemctl", "status", "--no-pager", "--full", "sshd.service"]
    assert kwargs.get("shell", False) is False
    assert result["unit"] == "sshd.service"
    assert result["status"] == "status output"


def test_service_status_accepts_valid_unit_names():
    with patch.object(services.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")):
        for good in ["sshd.service", "docker.service", "my-app_1.service", "template@1.service"]:
            result = services.service_status(good)
            assert "error" not in result, good


# ---------------------------------------------------------------------------
# network.py
# ---------------------------------------------------------------------------


def test_recent_journal_errors_rejects_bad_since_and_priority():
    result = network.recent_journal_errors(since="1 hour; rm -rf /", priority="err")
    assert "error" in result

    result = network.recent_journal_errors(since="1h", priority="not-a-real-priority")
    assert "error" in result


@patch.object(network.subprocess, "run")
def test_recent_journal_errors_builds_safe_argv(mock_run):
    mock_run.return_value = SimpleNamespace(returncode=0, stdout="log line 1\nlog line 2\n", stderr="")
    result = network.recent_journal_errors(since="2h", priority="warning")

    args, kwargs = mock_run.call_args
    argv = args[0]
    assert argv[0] == "journalctl"
    assert "--since=2 hours ago" in argv
    assert "--priority=warning" in argv
    assert kwargs.get("shell", False) is False
    assert result["count"] == 2


def test_network_connections_filters_to_listening_sockets():
    tcp_listen = SimpleNamespace(
        status="LISTEN",
        type=network.socket.SOCK_STREAM,
        laddr=SimpleNamespace(ip="0.0.0.0", port=22),
        pid=123,
    )
    tcp_established = SimpleNamespace(
        status="ESTABLISHED",
        type=network.socket.SOCK_STREAM,
        laddr=SimpleNamespace(ip="10.0.0.1", port=54321),
        pid=456,
    )
    udp_bound = SimpleNamespace(
        status="NONE",
        type=network.socket.SOCK_DGRAM,
        laddr=SimpleNamespace(ip="0.0.0.0", port=53),
        pid=789,
    )

    with (
        patch.object(network.psutil, "net_connections", return_value=[tcp_listen, tcp_established, udp_bound]),
        patch.object(network.psutil, "Process") as mock_process_cls,
    ):
        mock_process_cls.return_value.name.return_value = "sshd"
        result = network.network_connections()

    ports = {s["local_port"] for s in result["listening_sockets"]}
    assert ports == {22, 53}
    assert result["count"] == 2
