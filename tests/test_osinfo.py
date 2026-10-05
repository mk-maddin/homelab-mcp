import subprocess
from unittest.mock import Mock
import pytest
from homelab_mcp.tools import osinfo

def done(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)

def test_uname(monkeypatch):
    run = Mock(return_value=done(stdout="Linux test\n")); monkeypatch.setattr(osinfo.subprocess, "run", run)
    assert osinfo.uname_info()["output"] == "Linux test"
    run.assert_called_once_with(["uname", "-a"], capture_output=True, text=True, timeout=30, check=False)

def test_dpkg_filter_literal_case_insensitive(monkeypatch):
    monkeypatch.setattr(osinfo.subprocess, "run", Mock(return_value=done(stdout="ii Bash 1 amd64 shell\nii grep 1 amd64 search\n")))
    assert osinfo.dpkg_packages("bash")["lines"] == ["ii Bash 1 amd64 shell"]

def test_dpkg_unfiltered_capped(monkeypatch):
    output = "\n".join(f"ii pkg-{n} 1 amd64 x" for n in range(501))
    monkeypatch.setattr(osinfo.subprocess, "run", Mock(return_value=done(stdout=output)))
    result = osinfo.dpkg_packages(); assert result["count"] == 500 and result["truncated"] is True

@pytest.mark.parametrize("match", ["x;id", "$(id)", "x|cat", "x`id`", "x\nroot"])
def test_match_injection_rejected(match):
    assert "error" in osinfo.dpkg_packages(match)

def test_dmidecode_requires_match():
    assert osinfo.dmidecode_search("")["error"] == "match is required"

@pytest.mark.parametrize("value", [-1, 21, 1.5, "1", True])
def test_dmidecode_context_validation(value):
    assert "error" in osinfo.dmidecode_search("Product", after_lines=value)

def test_dmidecode_context_and_deduplication(monkeypatch):
    monkeypatch.setattr(osinfo.subprocess, "run", Mock(return_value=done(stdout="zero\nProduct A\nmiddle\nProduct B\nend\n")))
    result = osinfo.dmidecode_search("Product", 1, 1)
    assert result["lines"] == ["zero", "Product A", "middle", "Product B", "end"]

def test_dmidecode_permission_error(monkeypatch):
    monkeypatch.setattr(osinfo.subprocess, "run", Mock(return_value=done(stderr="Permission denied", returncode=1)))
    assert "root or equivalent privileges" in osinfo.dmidecode_search("Product")["error"]
