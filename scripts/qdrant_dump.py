#!/usr/bin/env python
"""Export/import a Qdrant collection snapshot (the database dump).

Qdrant snapshots are native, consistent collection dumps.  Both subcommands
talk to the running Qdrant container over HTTP only (``docker compose up -d
qdrant``) — no shared filesystem is required:

- ``export``  — create a snapshot of a collection on the server and download
                it into ``--dir`` (default ``./dumps``).
- ``import``  — upload a snapshot file into the server's snapshot storage and
                recover the collection from it (``--replace`` drops an
                existing collection first).

There is no other database mode; the dump lives in exactly one file per
export, e.g. ``dumps/arasaac_en-<uid>-<ts>.snapshot``.

Examples::

    docker compose up -d qdrant
    uv run python scripts/qdrant_dump.py export
    uv run python scripts/qdrant_dump.py export --collection arasaac_en
    uv run python scripts/qdrant_dump.py import dumps/arasaac_en-….snapshot
    uv run python scripts/qdrant_dump.py import old.snapshot --collection arasaac_en --replace
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arasaac_mcp.vector import (
    DEFAULT_COLLECTION,
    collection_name,
    qdrant_url,
)

#: Exit codes, mirroring the other scripts.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

#: Snapshot storage lives inside the qdrant volume.
DEFAULT_DUMP_DIR = Path("dumps")


def export_snapshot(url: str, collection: str, dump_dir: Path, timeout: float) -> tuple[Path, int]:
    """Create a snapshot of ``collection`` and download it to ``dump_dir``.

    Returns ``(local_path, size_in_bytes)``.
    """
    from qdrant_client import QdrantClient

    dump_dir.mkdir(parents=True, exist_ok=True)
    client = QdrantClient(url, timeout=int(timeout))
    description = client.create_snapshot(collection, wait=True)
    if description is None:
        raise RuntimeError(f"Qdrant did not create a snapshot of {collection!r}")
    name = description.name
    url_base = url.rstrip("/")
    request = urllib.request.Request(
        f"{url_base}/collections/{collection}/snapshots/{name}",
        headers={"User-Agent": "arasaac-mcp"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read()
    target = dump_dir / name
    target.write_bytes(data)
    return target, len(data)


def _upload_multipart(url: str, field: str, filename: str, data: bytes, timeout: float) -> str:
    boundary = uuid.uuid4().hex
    body = bytearray()
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        (
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
    )
    body.extend(data)
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        url,
        data=bytes(body),
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "arasaac-mcp",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def import_snapshot(
    url: str,
    path: Path,
    collection: str,
    *,
    replace: bool,
    timeout: float,
) -> None:
    """Upload ``path`` and let the server recover ``collection`` from it.

    The upload (``POST …/snapshots/upload``) stores the snapshot and recovers
    the collection from it in one step — the file never has to be visible to
    the server's own filesystem.
    """
    from qdrant_client import QdrantClient

    data = path.read_bytes()
    url_base = url.rstrip("/")
    client = QdrantClient(url, timeout=int(timeout))
    if client.collection_exists(collection):
        if not replace:
            raise RuntimeError(
                f"collection {collection!r} already exists; use --replace to overwrite it"
            )
        client.delete_collection(collection)
    payload = _upload_multipart(
        f"{url_base}/collections/{collection}/snapshots/upload",
        "snapshot",
        path.name,
        data,
        timeout,
    )
    answer = json.loads(payload) if payload else {}
    if answer.get("status") != "ok" or answer.get("result") is not True:
        raise RuntimeError(f"unexpected upload response: {payload[:200]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="qdrant-dump",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    export_parser = subparsers.add_parser(
        "export", help="Create and download a collection snapshot"
    )
    import_parser = subparsers.add_parser("import", help="Recover a collection from a snapshot")
    import_parser.add_argument(
        "snapshot", help="Snapshot file inside --dir (e.g. arasaac_en-…snapshot)"
    )
    for sub in (export_parser, import_parser):
        sub.add_argument("--qdrant-url", default=qdrant_url())
        sub.add_argument("--collection", default=collection_name() or DEFAULT_COLLECTION)
        sub.add_argument("--dir", type=Path, default=DEFAULT_DUMP_DIR)
        sub.add_argument("--timeout", type=float, default=120.0)
    import_parser.add_argument(
        "--replace",
        action="store_true",
        help="Drop an existing collection before recovering",
    )

    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            target, size = export_snapshot(args.qdrant_url, args.collection, args.dir, args.timeout)
            print(f"exported {args.collection} -> {target} ({size} bytes)")
        else:
            path = Path(args.snapshot)
            if not path.is_absolute():
                path = Path(args.dir) / path
            if not path.is_file():
                print(f"error: snapshot not found: {path}", file=sys.stderr)
                return EXIT_USAGE
            import_snapshot(
                args.qdrant_url,
                path,
                args.collection,
                replace=args.replace,
                timeout=args.timeout,
            )
            print(f"imported {path.name} -> {args.collection}")
    except (urllib.error.URLError, RuntimeError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FAILED
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
