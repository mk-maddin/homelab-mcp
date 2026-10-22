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


def _numbered(tmp_path, count, trailing_newline=True):
    target = tmp_path / "log"
    text = "\n".join(f"line {n}" for n in range(1, count + 1))
    target.write_text(text + ("\n" if trailing_newline else ""))
    return target


def test_tail_returns_last_lines(tmp_path):
    result = files.tail_file(str(_numbered(tmp_path, 50)), lines=3)
    assert result["content"] == "line 48\nline 49\nline 50"
    assert result["lines_returned"] == 3 and result["truncated"] is True


def test_tail_without_trailing_newline(tmp_path):
    result = files.tail_file(str(_numbered(tmp_path, 5, trailing_newline=False)), lines=2)
    assert result["content"] == "line 4\nline 5"


def test_tail_short_file_not_truncated(tmp_path):
    result = files.tail_file(str(_numbered(tmp_path, 3)), lines=100)
    assert result["content"] == "line 1\nline 2\nline 3"
    assert result["truncated"] is False


def test_tail_exact_line_count_not_truncated(tmp_path):
    result = files.tail_file(str(_numbered(tmp_path, 3)), lines=3)
    assert result["lines_returned"] == 3 and result["truncated"] is False


def test_tail_large_file_crosses_blocks(tmp_path):
    result = files.tail_file(str(_numbered(tmp_path, 5000)), lines=1000)
    expected = "\n".join(f"line {n}" for n in range(4001, 5001))
    assert result["content"] == expected and result["truncated"] is True


def test_tail_lines_are_clamped(tmp_path):
    target = _numbered(tmp_path, 1500)
    assert files.tail_file(str(target), lines=99999)["lines_returned"] == 1000
    assert files.tail_file(str(target), lines=0)["lines_returned"] == 1


def test_tail_empty_file(tmp_path):
    target = tmp_path / "empty"; target.write_text("")
    result = files.tail_file(str(target))
    assert result["content"] == "" and result["truncated"] is False


def test_tail_single_huge_line_is_capped(tmp_path):
    target = tmp_path / "huge"; target.write_text("a" * (files._MAX_READ_BYTES + 5000))
    result = files.tail_file(str(target), lines=1)
    assert result["bytes_returned"] == files._MAX_READ_BYTES and result["truncated"] is True


def test_tail_rejects_binary_invalid_lines_and_denied(monkeypatch, tmp_path):
    binary = tmp_path / "bin"; binary.write_bytes(b"ab\x00cd\n")
    assert files.tail_file(str(binary))["error"] == "binary files are not supported"
    assert "error" in files.tail_file(str(_numbered(tmp_path, 2)), lines="3")
    assert "error" in files.tail_file(str(tmp_path))
    secret = tmp_path / "secret"; secret.write_text("x\n")
    monkeypatch.setenv("HOMELAB_MCP_DENIED_FILES", str(secret))
    assert "denied" in files.tail_file(str(secret))["error"]
