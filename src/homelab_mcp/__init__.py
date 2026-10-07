"""homelab-mcp: a read-only MCP server for inspecting a Linux home server."""

__version__ = "0.1.0"


def get_git_commit() -> str:
    """Return the short git commit id of this checkout, or "unknown".

    ``HOMELAB_MCP_GIT_COMMIT`` takes precedence (useful when deployed without
    a ``.git`` directory); otherwise ``git rev-parse --short HEAD`` is run in
    the package's directory.
    """
    import os
    import subprocess
    from pathlib import Path

    override = os.environ.get("HOMELAB_MCP_GIT_COMMIT", "").strip()
    if override:
        return override
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() or "unknown"
