"""Tests for the allowlisted VM serial-console tool.

The happy-path tests run the real pty/subprocess code against a fake `virsh`
executable that behaves like `virsh console` (banner, raw tty, reads one
line, answers, exits on Ctrl-]).
"""
from __future__ import annotations

import stat
import sys
from unittest.mock import Mock

import pytest

from homelab_mcp.tools import vmconsole

FAKE_VIRSH = '''#!{python}
import sys, os, tty, time
if sys.argv[1:2] != ["console"] or len(sys.argv) != 3:
    sys.stderr.write("bad args\\n"); sys.exit(2)
if sys.argv[2] == "missing":
    sys.stderr.write("error: failed to get domain 'missing'\\n"); sys.exit(1)
tty.setraw(0)
out = sys.stdout
out.write("Connected to domain '%s'\\r\\nEscape character is ^] (Ctrl + ])\\r\\n" % sys.argv[2]); out.flush()
buf = b""
while True:
    ch = os.read(0, 1)
    if ch == b"\\x1d" or not ch:
        sys.exit(0)
    if ch == b"\\n":
        cmd = buf.decode(); buf = b""
        if cmd == "hang":
            while True:
                out.write("tick\\r\\n"); out.flush(); time.sleep(0.05)
        out.write("%s\\r\\nreply to: %s\\r\\nroot@vm:~# " % (cmd, cmd)); out.flush()
    else:
        buf += ch
'''


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch, tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    virsh = bindir / "virsh"
    virsh.write_text(FAKE_VIRSH.format(python=sys.executable))
    virsh.chmod(virsh.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bindir}:/usr/bin:/bin")
    monkeypatch.setattr(vmconsole, "_IDLE_SECONDS", 0.4)
    monkeypatch.setattr(vmconsole, "_TIMEOUT_SECONDS", 1.5)
    log = tmp_path / "console.log"
    monkeypatch.setenv("HOMELAB_MCP_KVM_VMS", "vm1, vm-2,bad name,-oProxy,missing,vm1")
    monkeypatch.setenv("HOMELAB_MCP_KVM_LOG", str(log))
    return log


def test_loads_valid_unique_vm_names(configured) -> None:
    assert vmconsole.load_kvm_vms() == ["vm1", "vm-2", "missing"]


def test_unconfigured_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOMELAB_MCP_KVM_VMS", raising=False)
    monkeypatch.delenv("HOMELAB_MCP_KVM_LOG", raising=False)
    assert "not configured" in vmconsole.run_vm_console_command("vm1", "ls")["error"]
    assert "none configured" in vmconsole.tool_description()


def test_rejects_unknown_vm_without_running(configured, monkeypatch) -> None:
    popen = Mock()
    monkeypatch.setattr(vmconsole.subprocess, "Popen", popen)
    result = vmconsole.run_vm_console_command("other", "ls")
    assert result == {"error": "unknown vm", "available_vms": ["vm1", "vm-2", "missing"]}
    assert "error" in vmconsole.run_vm_console_command("-oProxyCommand=x", "ls")
    popen.assert_not_called()


@pytest.mark.parametrize("command", ["", "   ", "a\x00b", "x" * 5000, "a\nb", "a\rb"])
def test_rejects_bad_commands(configured, monkeypatch, command) -> None:
    popen = Mock()
    monkeypatch.setattr(vmconsole.subprocess, "Popen", popen)
    assert "error" in vmconsole.run_vm_console_command("vm1", command)
    popen.assert_not_called()
    assert not configured.exists()


def test_runs_command_on_console_and_logs_it(configured) -> None:
    result = vmconsole.run_vm_console_command("vm1", "uname -a")
    assert result["vm"] == "vm1"
    assert result["returncode"] == 0
    assert "reply to: uname -a" in result["stdout"]
    assert "\r" not in result["stdout"]
    assert result["timed_out"] is False and result["truncated"] is False
    assert "stderr" not in result
    text = configured.read_text()
    assert text.splitlines()[0].endswith("] vm1$ uname -a")
    assert "reply to: uname -a" in text
    assert "exit" not in text.lower()


def test_log_is_appended_not_overwritten(configured) -> None:
    configured.write_text("old content\n")
    vmconsole.run_vm_console_command("vm1", "first")
    vmconsole.run_vm_console_command("vm-2", "second")
    lines = configured.read_text().splitlines()
    assert lines[0] == "old content"
    assert sum("vm1$ first" in line for line in lines) == 1
    assert sum("vm-2$ second" in line for line in lines) == 1


def test_virsh_error_goes_to_stderr_and_log(configured) -> None:
    result = vmconsole.run_vm_console_command("missing", "ls")
    assert result["returncode"] == 1
    assert result["stdout"] == ""
    assert "failed to get domain" in result["stderr"]
    text = configured.read_text()
    assert text.splitlines()[0].endswith("] missing$ ls")
    assert "failed to get domain" in text


def test_total_timeout_stops_endless_output(configured) -> None:
    result = vmconsole.run_vm_console_command("vm1", "hang")
    assert result["timed_out"] is True
    assert "tick" in result["stdout"]


def test_command_logged_before_execution(configured, monkeypatch) -> None:
    seen = {}

    def fake_run(vm, command):
        seen["log"] = configured.read_text()
        return 0, "out\n", "", False

    monkeypatch.setattr(vmconsole, "_run_console", fake_run)
    vmconsole.run_vm_console_command("vm1", "id")
    assert seen["log"].endswith("] vm1$ id\n")


def test_output_returned_is_capped_but_logged_in_full(configured, monkeypatch) -> None:
    big = "x" * (vmconsole._MAX_OUTPUT_CHARS + 10)
    monkeypatch.setattr(vmconsole, "_run_console", lambda vm, c: (0, big, "", False))
    result = vmconsole.run_vm_console_command("vm1", "cat big")
    assert len(result["stdout"]) == vmconsole._MAX_OUTPUT_CHARS
    assert result["truncated"] is True
    assert big in configured.read_text()


def test_missing_virsh_binary(configured, monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/nonexistent")
    result = vmconsole.run_vm_console_command("vm1", "ls")
    assert "failed to run virsh console" in result["error"]


def test_description_lists_vms(configured) -> None:
    assert "vm1, vm-2, missing" in vmconsole.tool_description()
