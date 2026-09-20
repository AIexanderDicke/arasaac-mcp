#!/usr/bin/env bash
# Start (or restart) the ARASAAC MCP stack without breaking the VS Code
# forwarded port.
#
#   scripts/mcp_up.sh          # start both tmux sessions if missing
#   scripts/mcp_up.sh --force  # restart the MCP server (relay is left alone)
#
# The relay permanently owns the forwarded port (default 8000); the MCP
# server listens on an internal port (default 8001) behind it.
set -euo pipefail

PORT="${ARASAAC_PORT:-8000}"
INTERNAL="${ARASAAC_INTERNAL_PORT:-8001}"
HOST="${ARASAAC_HOST:-127.0.0.1}"
RELAY_SESSION="${ARASAAC_RELAY_SESSION:-arasaac-relay}"
MCP_SESSION="${ARASAAC_MCP_SESSION:-arasaac-mcp}"
cd "$(dirname "$0")/.."

if ! tmux has-session -t "$RELAY_SESSION" 2>/dev/null; then
  tmux new-session -d -s "$RELAY_SESSION" \
    "uv run python scripts/port_relay.py --host 0.0.0.0 --port $PORT \
     --upstream-host $HOST --upstream-port $INTERNAL > /tmp/arasaac-relay.log 2>&1"
  echo "started relay: 0.0.0.0:$PORT -> $HOST:$INTERNAL"
fi

if [[ "${1:-}" == "--force" ]]; then
  tmux kill-session -t "$MCP_SESSION" 2>/dev/null || true
  sleep 1
fi

if ! tmux has-session -t "$MCP_SESSION" 2>/dev/null; then
  tmux new-session -d -s "$MCP_SESSION" \
    "uv run arasaac-mcp --transport http --host $HOST --port $INTERNAL \
     > /tmp/arasaac-mcp.log 2>&1"
  echo "started server: $HOST:$INTERNAL"
fi

sleep 8
if uv run python - "$PORT" <<'PY'
import asyncio, sys
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async def main():
    url = f"http://127.0.0.1:{sys.argv[1]}/mcp"
    async with streamable_http_client(url) as (r, w):
        async with ClientSession(r, w) as s:
            info = await s.initialize()
            print("ok:", info.server_info.name, info.server_info.version)

asyncio.run(main())
PY
then
  echo "MCP reachable on http://localhost:$PORT/mcp"
else
  echo "MCP NOT reachable - see /tmp/arasaac-mcp.log and /tmp/arasaac-relay.log" >&2
  exit 1
fi
