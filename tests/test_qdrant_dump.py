"""Snapshot dump round-trip against a real Qdrant server.

Skipped unless a Qdrant is reachable at ``ARASAAC_QDRANT_URL`` (default the
compose container: ``docker compose up -d qdrant``) — the in-process local
mode cannot serve snapshots.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from helpers import HashingEmbedder
from qdrant_client import QdrantClient

pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect in the local Qdrant")

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    path = REPO_ROOT / "scripts" / "qdrant_dump.py"
    spec = importlib.util.spec_from_file_location("qdrant_dump", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script() -> ModuleType:
    return _load()


@pytest.fixture
def dump_dir(tmp_path: Path) -> Path:
    return tmp_path / "dumps"


@pytest.fixture
def server_url() -> str:
    from arasaac_mcp.vector import qdrant_url

    url = qdrant_url()
    try:
        QdrantClient(url, timeout=2).get_collections()
    except Exception:
        pytest.skip(f"no Qdrant server at {url} (docker compose up -d qdrant)")
    return url


def _target_collection() -> str:
    import uuid

    return f"dump_test_{uuid.uuid4().hex[:8]}"


def test_export_then_import_round_trip(script: ModuleType, server_url: str, dump_dir: Path) -> None:
    from arasaac_mcp.vector import PicRecord, VectorIndex

    collection = _target_collection()
    index = VectorIndex(QdrantClient(server_url, timeout=30), collection)
    index.ensure_collection(HashingEmbedder.DIM)
    record = PicRecord(
        pic_id=4242,
        label="Anker",
        word="Anker",
        description="A small boat anchor.",
        usage="Shipping, hope symbol.",
        synonyms=("anchor",),
        keywords=("Anker",),
        tags=(),
        categories=(),
    )
    embedder = HashingEmbedder()
    text = embedder.embed([record.text_document()])
    syn = embedder.embed([record.syn_document()])
    index.upsert([record], [{"text": text[0], "syn": syn[0]}])
    assert index.count() == 1

    target, size = script.export_snapshot(server_url, collection, dump_dir, timeout=60)
    assert size > 0 and target.is_file()

    restored = _target_collection()
    script.import_snapshot(
        server_url,
        target,
        restored,
        replace=False,
        timeout=60,
    )
    check = VectorIndex(QdrantClient(server_url, timeout=30), restored)
    assert check.count() == 1
    assert check.existing_ids() == {4242}

    import_snapshot_raises = script.import_snapshot
    with pytest.raises(Exception, match="already exists"):
        import_snapshot_raises(server_url, target, restored, replace=False, timeout=60)
    import_snapshot_raises(server_url, target, restored, replace=True, timeout=60)
    assert VectorIndex(QdrantClient(server_url, timeout=30), restored).count() == 1

    # cleanup
    client = QdrantClient(server_url, timeout=30)
    for name in (collection, restored):
        client.delete_collection(name)


def test_import_of_missing_file(script: ModuleType, tmp_path: Path) -> None:
    assert (
        script.main(
            ["import", "nope.snapshot", "--dir", str(tmp_path), "--qdrant-url", "http://offline"]
        )
        == 2
    )
