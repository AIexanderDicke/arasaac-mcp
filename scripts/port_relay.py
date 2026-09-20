#!/usr/bin/env python3
"""Stable TCP relay in front of the ARASAAC MCP server.

The VS Code port forwarder binds to a port once and does not retry if the
upstream listener disappears. Restarting the MCP server therefore silently
kills the forwarded port. This relay keeps a permanent listener on the
forwarded port (default 8000) and re-resolves its upstream target on every
connection, so the real server can be restarted freely.

Run it in tmux and leave it running:

    tmux new -d -s arasaac-relay \
        "uv run python scripts/port_relay.py > /tmp/arasaac-relay.log 2>&1"

The MCP server should then listen on a different internal port, e.g. 8001:

    uv run arasaac-mcp --transport http --host 127.0.0.1 --port 8001
"""

from __future__ import annotations

import argparse
import contextlib
import selectors
import socket
import sys
import threading

BUFFER = 65536


def pump(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(BUFFER)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for sock in (src, dst):
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)


def handle(client: socket.socket, upstream_host: str, upstream_port: int) -> None:
    try:
        upstream = socket.create_connection((upstream_host, upstream_port), timeout=10)
    except OSError as exc:
        print(f"[relay] upstream {upstream_host}:{upstream_port} unavailable: {exc}", flush=True)
        client.close()
        return
    upstream.settimeout(None)
    client.settimeout(None)
    t = threading.Thread(target=pump, args=(client, upstream), daemon=True)
    t.start()
    pump(upstream, client)
    t.join(timeout=1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0", help="address to listen on")
    parser.add_argument("--port", type=int, default=8000, help="port to listen on")
    parser.add_argument("--upstream-host", default="127.0.0.1")
    parser.add_argument("--upstream-port", type=int, default=8001)
    args = parser.parse_args()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(64)
    print(
        f"[relay] listening on {args.host}:{args.port} -> "
        f"{args.upstream_host}:{args.upstream_port}",
        flush=True,
    )

    sel = selectors.DefaultSelector()
    sel.register(server, selectors.EVENT_READ)
    while True:
        for key, _ in sel.select():
            assert isinstance(key.fileobj, socket.socket)
            client, _ = key.fileobj.accept()
            threading.Thread(
                target=handle,
                args=(client, args.upstream_host, args.upstream_port),
                daemon=True,
            ).start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
