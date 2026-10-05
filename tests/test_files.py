from pathlib import Path
import pytest
from homelab_mcp.tools import files

def test_additional_denied_file(monkeypatch, tmp_path):
    target = tmp_path / "secret"; target.write_text("secret")
    monkeypatch.setenv("HOMELAB_MCP_DENIED_FILES", str(target))
    assert files._resolve_requested_path(str(target))[0] is None

def test_denied_folder_blocks_child(monkeypatch, tmp_path):
    folder = tmp_path / "private"; folder.mkdir(); child = folder / "x"; child.write_text("x")
    monkeypatch.setenv("HOMELAB_MCP_DENIED_FOLDERS", str(folder))
    assert files._resolve_requested_path(str(child))[0] is None

def test_symlink_cannot_bypass_denied_file(monkeypatch, tmp_path):
    target = tmp_path / "secret"; target.write_text("secret"); link = tmp_path / "link"; link.symlink_to(target)
    monkeypatch.setenv("HOMELAB_MCP_DENIED_FILES", str(target))
    assert files._resolve_requested_path(str(link))[0] is None

def test_relative_path_rejected():
    assert files._resolve_requested_path("relative")[1] == "path must be absolute"

def test_permitted_text_file(tmp_path):
    target = tmp_path / "ok"; target.write_text("allowed")
    assert files.read_file(str(target))["content"] == "allowed"

def test_binary_rejected(tmp_path):
    target = tmp_path / "bin"; target.write_bytes(b"a\x00b")
    assert files.read_file(str(target))["error"] == "binary files are not supported"

def test_read_limit(tmp_path):
    target = tmp_path / "large"; target.write_text("abcdefgh")
    result = files.read_file(str(target), max_bytes=4)
    assert result["content"] == "abcd" and result["truncated"] is True

def test_directory_limit(tmp_path):
    for n in range(3): (tmp_path / str(n)).write_text("x")
    result = files.list_directory(str(tmp_path), max_entries=2)
    assert result["count"] == 2 and result["truncated"] is True
