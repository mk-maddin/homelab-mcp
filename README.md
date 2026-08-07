# homelab-mcp

A local-network [MCP](https://modelcontextprotocol.io) server that lets an
MCP client (Claude Code, Claude Desktop) inspect a Linux home server's
health over the network — uptime, load, memory, disk space, Docker
containers, systemd services, journal errors, and listening ports.

Built with [FastMCP](https://github.com/jlowin/fastmcp), the official
Python MCP SDK's high-level server framework.

**This server is strictly read-only.** No tool it exposes can modify
system state, restart a service, start/stop a container, or execute an
arbitrary command. It exists purely so you can ask "why is my server
using so much CPU right now?" or "did that container crash again?" from a
Claude client, without SSHing in yourself.

## Security model

- **Bearer token auth.** Every request must include
  `Authorization: Bearer <token>`. The token lives in `HOMELAB_MCP_TOKEN`
  (loaded from a `.env` file, never committed) and is checked with
  `hmac.compare_digest` to avoid timing attacks. Missing or wrong tokens
  get a `401`.
- **Read-only by design.** Every tool is implemented with a safe,
  non-mutating API (`psutil`, `shutil.disk_usage`, `docker-py`) or, where a
  subprocess is unavoidable (`systemctl`, `journalctl`), a fixed argument
  list with `shell=True` never used and any user-supplied parameter
  validated against a strict allowlist/regex before it touches the
  command line.
- **No rate limiting or lockout.** This server does not throttle or lock
  out repeated failed auth attempts. **Do not expose it on the open
  internet, even with the token in place.** Run it behind
  [Tailscale](https://tailscale.com/) or WireGuard, or bind it to a
  LAN-only / loopback interface via `HOMELAB_MCP_HOST`. Treat the bearer
  token like a password: anyone who has it and can reach the port has
  full read access to your server's health data.

## Setup

Requires Python 3.11+ and [`uv`](https://docs.astral.sh/uv/) (or plain
`pip`).

```bash
git clone https://github.com/VedantDesai11/homelab-mcp.git
cd homelab-mcp

cp .env.example .env
# edit .env: set HOMELAB_MCP_TOKEN to a strong random value, e.g.
#   python3 -c "import secrets; print(secrets.token_urlsafe(32))"

uv sync
# or: pip install -e .
```

### Running locally

```bash
uv run homelab-mcp
# or: uv run python -m homelab_mcp.server
```

By default it binds `0.0.0.0:8811`. Override with `HOMELAB_MCP_HOST` /
`HOMELAB_MCP_PORT` in `.env` or the environment. The server exits
immediately with a clear error if `HOMELAB_MCP_TOKEN` is unset.

The MCP endpoint is served at `http://<host>:<port>/mcp` over Streamable
HTTP.

### Running via systemd

For a persistent deployment on the home server itself:

1. Copy the project to `/opt/homelab-mcp` (or wherever you like) and run
   `uv sync` there so `/opt/homelab-mcp/.venv` exists.
2. Copy `.env.example` to `/opt/homelab-mcp/.env` and fill in a real
   token.
3. Run the installer as root:

   ```bash
   sudo ./deploy/install.sh
   ```

   This creates a dedicated non-root `homelab-mcp` system user (if it
   doesn't already exist), installs `deploy/homelab-mcp.service` to
   `/etc/systemd/system/`, reloads systemd, and enables + starts the
   service (restarts automatically on failure).

   If you want `list_containers` / `container_logs` to work, add the
   service user to the `docker` group so it can reach the Docker socket:

   ```bash
   sudo usermod -aG docker homelab-mcp
   sudo systemctl restart homelab-mcp
   ```

## Connecting Claude Code / Claude Desktop

Add an MCP server entry pointing at the running instance, with the bearer
token as a header. For example, in Claude Code's MCP config:

```json
{
  "mcpServers": {
    "homelab": {
      "url": "http://your-server-hostname:8811/mcp",
      "headers": {
        "Authorization": "Bearer <your HOMELAB_MCP_TOKEN>"
      }
    }
  }
}
```

If you're on Tailscale, use the server's Tailscale hostname/IP so the
connection never leaves your tailnet.

## Tools

| Tool | Description |
|---|---|
| `system_status()` | Uptime, load average (1/5/15m), memory used/total, CPU count and utilization. |
| `disk_usage(path="/")` | Total/used/free/percent disk space for a given mount path. |
| `list_containers()` | Name, image, status, and port mappings for all Docker containers (running and stopped). |
| `container_logs(name, lines=100)` | Tail of logs for one named Docker container. |
| `list_services()` | All systemd service units with their load/active/sub state. |
| `service_status(unit)` | Detailed `systemctl status` output for one systemd service unit. |
| `recent_journal_errors(since="1h", priority="err")` | Recent journal entries at or above a given syslog priority. |
| `network_connections()` | Listening TCP/UDP sockets: local address, port, and owning process where permitted. |

## Development

```bash
uv sync --group dev
uv run pytest
```

Tests mock `psutil`, `docker-py`, and `subprocess` so the suite never
touches the real system, a real Docker daemon, or spawns real
subprocesses.
