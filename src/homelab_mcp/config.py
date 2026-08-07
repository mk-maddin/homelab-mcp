"""Environment configuration for homelab-mcp.

Settings are loaded from the process environment (via a .env file if
present) and validated explicitly by calling ``load_settings()``. The
server entrypoint calls this at startup and fails loudly (exits non-zero)
if required settings are missing -- it is intentionally NOT validated at
module import time so that other modules (and tests) can be imported
without a .env file present.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    token: str
    host: str
    port: int


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"FATAL: environment variable {name}={raw!r} is not a valid integer.", file=sys.stderr)
        raise SystemExit(1)


def load_settings() -> Settings:
    """Load and validate settings from the environment.

    Exits the process with a clear error message if HOMELAB_MCP_TOKEN is
    unset or blank -- this server must never start without a token.
    """
    load_dotenv()

    token = os.environ.get("HOMELAB_MCP_TOKEN", "").strip()
    if not token:
        print(
            "FATAL: environment variable HOMELAB_MCP_TOKEN is not set. "
            "Create a .env file (see .env.example) or export it before starting the server.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    host = os.environ.get("HOMELAB_MCP_HOST", "0.0.0.0").strip() or "0.0.0.0"
    port = _get_int("HOMELAB_MCP_PORT", 8811)

    return Settings(token=token, host=host, port=port)
