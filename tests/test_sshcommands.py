"""Tests for the allowlisted SSH command tool."""
from __future__ import annotations

import subprocess
from unittest.mock import Mock

import pytest

from homelab_mcp.tools import sshcommands


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch, tmp_path):
    log = tmp_path / "ssh.log"
    monkeypatch.setenv("HOMELAB_MCP_SSH_VMS", "vm1, vm-2,bad name,-oProxy,vm1")
    monkeypatch.setenv("HOMELAB_MCP_SSH_LOG", str(log))
    return log


def test_loads_valid_unique_vm_names(configured) -> None:
    assert sshcommands.load_ssh_vms() == ["vm1", "vm-2"]


def test_unconfigured_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOMELAB_MCP_SSH_VMS", raising=False)
    monkeypatch.delenv("HOMELAB_MCP_SSH_LOG", raising=False)
    assert "not configured" in sshcommands.run_ssh_command("vm1", "ls")["error"]
    assert "none configured" in sshcommands.tool_description()


def test_rejects_unknown_vm_without_running(configured, monkeypatch) -> None:
    run = Mock()
    monkeypatch.setattr(sshcommands.subprocess, "run", run)
    result = sshcommands.run_ssh_command("other", "ls")
    assert result == {"error": "unknown vm", "available_vms": ["vm1", "vm-2"]}
    run.assert_not_called()


def test_rejects_option_like_vm(configured, monkeypatch) -> None:
    run = Mock()
    monkeypatch.setattr(sshcommands.subprocess, "run", run)
    assert "error" in sshcommands.run_ssh_command("-oProxyCommand=x", "ls")
    run.assert_not_called()


@pytest.mark.parametrize("command", ["", "   ", "a\x00b", "x" * 5000])
def test_rejects_bad_commands(configured, monkeypatch, command) -> None:
    run = Mock()
    monkeypatch.setattr(sshcommands.subprocess, "run", run)
    assert "error" in sshcommands.run_ssh_command("vm1", command)
    run.assert_not_called()


def test_runs_ssh_without_shell_and_writes_stdout_to_log(configured, monkeypatch) -> None:
    def fake_run(argv, stdout, **kwargs):
        stdout.write("hello\n")
        return subprocess.CompletedProcess(argv, 0, None, "warn\n")

    run = Mock(side_effect=fake_run)
    monkeypatch.setattr(sshcommands.subprocess, "run", run)
    result = sshcommands.run_ssh_command("vm1", "echo 'hi there'; uptime")
    assert run.call_args.args[0] == [
        "ssh", "-o", "BatchMode=yes", "--", "vm1", "echo 'hi there'; uptime",
    ]
    assert run.call_args.kwargs.get("shell") is None
    assert configured.read_text() == "hello\n"
    assert result == {
        "vm": "vm1", "returncode": 0, "log": str(configured), "stderr": "warn",
    }


def test_log_is_overwritten(configured, monkeypatch) -> None:
    configured.write_text("old content\n")
    monkeypatch.setattr(
        sshcommands.subprocess, "run",
        Mock(return_value=subprocess.CompletedProcess([], 1, None, "")),
    )
    result = sshcommands.run_ssh_command("vm1", "false")
    assert configured.read_text() == ""
    assert result["returncode"] == 1 and "stderr" not in result


def test_timeout_and_os_errors(configured, monkeypatch) -> None:
    monkeypatch.setattr(
        sshcommands.subprocess, "run",
        Mock(side_effect=subprocess.TimeoutExpired("ssh", 120)),
    )
    assert "exceeded" in sshcommands.run_ssh_command("vm1", "sleep 999")["error"]
    monkeypatch.setattr(sshcommands.subprocess, "run", Mock(side_effect=OSError("no ssh")))
    assert "failed to run" in sshcommands.run_ssh_command("vm1", "ls")["error"]


def test_description_lists_vms(configured) -> None:
    assert "vm1, vm-2" in sshcommands.tool_description()
