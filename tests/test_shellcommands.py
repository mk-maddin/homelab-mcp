"""Tests for administrator-defined shell commands."""
from __future__ import annotations

import subprocess
from unittest.mock import Mock

import pytest

from homelab_mcp.tools import shellcommands


def completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def clear_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(shellcommands.os.environ):
        if name.startswith("HOMELAB_MCP_SHELL_COMMAND_"):
            monkeypatch.delenv(name, raising=False)


def test_loads_and_normalizes_valid_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_commands(monkeypatch)
    monkeypatch.setenv("HOMELAB_MCP_SHELL_COMMAND_DFH", "df -h /")
    monkeypatch.setenv("HOMELAB_MCP_SHELL_COMMAND_LSUSB", "lsusb")
    assert shellcommands.available_shell_command_aliases() == ["dfh", "lsusb"]


def test_does_not_expose_command_text(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_commands(monkeypatch)
    monkeypatch.setenv("HOMELAB_MCP_SHELL_COMMAND_DFH", "df -h /")
    result = shellcommands.list_shell_commands()
    assert result == {"commands": ["dfh"], "count": 1}
    assert "df -h /" not in repr(result)


def test_executes_exact_configured_command(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_commands(monkeypatch)
    monkeypatch.setenv("HOMELAB_MCP_SHELL_COMMAND_DFH", "df -h /")
    run = Mock(return_value=completed(stdout="Filesystem Use%\n/dev/sda 25%\n"))
    monkeypatch.setattr(shellcommands.subprocess, "run", run)
    result = shellcommands.run_shell_command("dfh")
    run.assert_called_once_with(
        ["/bin/sh", "-c", "df -h /"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result["count"] == 2


def test_literal_output_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_commands(monkeypatch)
    monkeypatch.setenv("HOMELAB_MCP_SHELL_COMMAND_LSUSB", "lsusb")
    monkeypatch.setattr(
        shellcommands.subprocess,
        "run",
        Mock(return_value=completed(stdout="Bus 1 Logitech\nBus 2 Linux Foundation\n")),
    )
    result = shellcommands.run_shell_command("lsusb", match="logitech")
    assert result["lines"] == ["Bus 1 Logitech"]


@pytest.mark.parametrize("match", ["x;id", "$(id)", "x|cat", "x`id`", "x\nroot"])
def test_filter_rejects_shell_control_characters(match: str) -> None:
    assert "error" in shellcommands.run_shell_command("dfh", match)


def test_unknown_alias_does_not_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_commands(monkeypatch)
    run = Mock()
    monkeypatch.setattr(shellcommands.subprocess, "run", run)
    result = shellcommands.run_shell_command("missing")
    assert result["error"] == "unknown shell-command alias"
    run.assert_not_called()


def test_tool_description_advertises_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_commands(monkeypatch)
    monkeypatch.setenv("HOMELAB_MCP_SHELL_COMMAND_DFH", "df -h /")
    description = shellcommands.tool_description()
    assert "dfh" in description
    assert "df -h /" not in description
