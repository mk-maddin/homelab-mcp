#!/usr/bin/env bash
# Installs the homelab-mcp systemd unit and starts the service.
#
# Assumes the project has already been deployed to /opt/homelab-mcp with a
# working virtualenv at /opt/homelab-mcp/.venv (e.g. via `uv sync`) and a
# populated /opt/homelab-mcp/.env (copy .env.example and fill it in).
#
# Run as root (or with sudo).

set -euo pipefail

UNIT_NAME="homelab-mcp.service"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
SERVICE_USER="homelab-mcp"
INSTALL_DIR="/opt/homelab-mcp"

if [[ "${EUID}" -ne 0 ]]; then
    echo "This script must be run as root (try: sudo ./install.sh)" >&2
    exit 1
fi

if [[ ! -f "${INSTALL_DIR}/.env" ]]; then
    echo "WARNING: ${INSTALL_DIR}/.env not found. Copy .env.example there and set HOMELAB_MCP_TOKEN before starting the service." >&2
fi

if ! id "${SERVICE_USER}" &>/dev/null; then
    echo "Creating dedicated non-root user '${SERVICE_USER}'..."
    useradd --system --no-create-home --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

if getent group systemd-journal &>/dev/null; then
    echo "Adding ${SERVICE_USER} to 'systemd-journal' group (required for recent_journal_errors)..."
    usermod -aG systemd-journal "${SERVICE_USER}"
else
    echo "WARNING: 'systemd-journal' group not found; recent_journal_errors will fail to read logs." >&2
fi

if getent group docker &>/dev/null; then
    echo "Adding ${SERVICE_USER} to 'docker' group (required for list_containers/container_logs)..."
    usermod -aG docker "${SERVICE_USER}"
else
    echo "Note: 'docker' group not found -- skipping (list_containers/container_logs will report Docker as unavailable)."
fi

echo "Installing ${UNIT_NAME} to /etc/systemd/system/..."
cp "${SCRIPT_DIR}/${UNIT_NAME}" "/etc/systemd/system/${UNIT_NAME}"

echo "Reloading systemd daemon..."
systemctl daemon-reload

echo "Enabling and starting ${UNIT_NAME}..."
systemctl enable --now "${UNIT_NAME}"

echo
echo "Status:"
systemctl status --no-pager "${UNIT_NAME}"
