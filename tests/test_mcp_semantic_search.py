"""The ``semantic_search_pictograms`` MCP tool, offline end to end.

Qdrant's in-process local mode stands in for the Docker database and the
deterministic :class:`HashingEmbedder` stands in for a real embedding model;
both are injected by monkeypatching the module's provider callables.
"""

from __future__ import annotations

import pytest
from fastmcp import Client
from helpers import HashingEmbedder
from qdrant_client import QdrantClient

from arasaac_mcp.catalog import Catalog
from arasaac_mcp.mcp.semantic_search_pictograms import search
from arasaac_mcp.mcp.server import create_server
from arasaac_mcp.vector import (
    PicRecord,
    VectorDBError,
    VectorIndex,
)

pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect in the local Qdrant")

DIM = HashingEmbedder.DIM


def make_record(pic_id: int, description: str, usage: str) -> PicRecord:
    return PicRecord(
        pic_id=pic_id,
        label="",
        word="",
        description=description,
        usage=usage,
        synonyms=(),
        keywords=(),
        tags=(),
        categories=(),
    )


@pytest.fixture
def seeded_index() -> VectorIndex:
    """A description index over the synthetic library (ids 1, 2, 4, 7)."""
    index = VectorIndex(QdrantClient(":memory:"), "semantic_col")
    index.ensure_collection(DIM)
    records = [
        make_record(1, "Rain falling from clouds over a meadow.", "Weather, not shower."),
        make_record(2, "A red car driving on a country road.", "Vehicle on road, not toy."),
        make_record(4, "A student writing at a desk.", "School desk work, not office."),
        make_record(7, "A green mountain with a snow cap.", "Hiking, skiing, nature."),
    ]
    embedder = HashingEmbedder()
    text = embedder.embed([r.text_document() for r in records])
    syn = embedder.embed([r.syn_document() for r in records])
    index.upsert(records, [{"text": a, "syn": b} for a, b in zip(text, syn, strict=True)])
    return index


def _module():
    import arasaac_mcp.mcp.semantic_search_pictograms as module

    return module


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch, seeded_index: VectorIndex) -> VectorIndex:
    """Route the tool's provider calls to the offline stand-ins."""
    module = _module()
    monkeypatch.setattr(module, "get_vector_index", lambda *a, **k: seeded_index)
    monkeypatch.setattr(module, "make_embedder", lambda *a, **k: HashingEmbedder())
    return seeded_index


# -- the search function --------------------------------------------------


def test_semantic_search_matches_words(catalog: Catalog, patched: VectorIndex) -> None:
    message = search(catalog, patched, HashingEmbedder(), "Regen weather")
    assert message.startswith("Found:")
    assert "Regen" in message
    assert "1_Regen.png" not in message


def test_labels_round_trip(catalog: Catalog, patched: VectorIndex) -> None:
    message = search(catalog, patched, HashingEmbedder(), "car road vehicle")
    label = next(line for line in message.splitlines() if "Auto" in line)
    shown = label.split(". ", 1)[1].split(" — ", 1)[0]
    resolved = catalog.resolve(shown)
    assert resolved.file == "2_Auto.png"


def test_semantic_search_empty_query(catalog: Catalog, patched: VectorIndex) -> None:
    assert search(catalog, patched, HashingEmbedder(), "  ") == "Empty search query."


def test_semantic_search_unknown_mode(catalog: Catalog, patched: VectorIndex) -> None:
    message = search(catalog, patched, HashingEmbedder(), "Auto", mode="quantum")
    assert "Unknown search mode" in message


def test_semantic_search_weak_matches_filtered(catalog: Catalog, patched: VectorIndex) -> None:
    # An unrelated query stays below every cosine the test embedder produces.
    message = search(
        catalog,
        patched,
        HashingEmbedder(),
        "crocodile chewing gum",
        min_score=0.9,
    )
    assert "No pictograms found" in message
    assert "search_pictograms" in message


def test_semantic_search_respects_limit(catalog: Catalog, patched: VectorIndex) -> None:
    message = search(catalog, patched, HashingEmbedder(), "school desk", limit=1)
    assert message.count("\n") == 1


def test_semantic_search_tag_filter(catalog: Catalog, patched: VectorIndex) -> None:
    # The synthetic index has no tags at all, so filtering by any tag yields nothing.
    message = search(
        catalog,
        patched,
        HashingEmbedder(),
        "Regen weather",
        tags="fahrzeug",
    )
    assert "No pictograms found" in message


def test_db_failure_reports_hint(catalog: Catalog, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()

    class Broken:
        def search(self, *args, **kwargs):
            raise VectorDBError("Qdrant is down")

    monkeypatch.setattr(module, "get_vector_index", lambda *a, **k: Broken())
    message = search(catalog, Broken(), HashingEmbedder(), "Regen")
    assert "Semantic search failed" in message
    assert "Qdrant is down" in message


def test_boost_reorders_with_query_words(monkeypatch: pytest.MonkeyPatch, catalog: Catalog) -> None:
    """A boosted density/index match wins when vector scores tie."""
    index = VectorIndex(QdrantClient(":memory:"), "boost_col")
    index.ensure_collection(DIM)
    records = [
        make_record(6, "A painting of a red ball.", "Colour, not sport."),
        make_record(1, "A painting of a red ball.", "Colour, not sport."),
    ]
    records[0] = PicRecord(
        pic_id=6,
        label="rot",
        word="rot",
        description=records[0].description,
        usage=records[0].usage,
        synonyms=(),
        keywords=("rot",),
        tags=("rot",),
        categories=(),
    )
    records[1] = PicRecord(
        pic_id=1,
        label="Regen",
        word="Regen",
        description=records[1].description,
        usage=records[1].usage,
        synonyms=(),
        keywords=("Regen",),
        tags=(),
        categories=(),
    )
    embedder = HashingEmbedder()
    text = embedder.embed([r.text_document() for r in records])
    syn = embedder.embed([r.syn_document() for r in records])
    index.upsert(records, [{"text": a, "syn": b} for a, b in zip(text, syn, strict=True)])
    message = search(
        catalog,
        index,
        embedder,
        "rot ball painting",
        boost=True,
    )
    assert message.splitlines()[1].split(". ", 1)[1].split(" — ", 1)[0] == "rot"


def test_filters_reach_the_index(
    monkeypatch: pytest.MonkeyPatch, seeded_index: VectorIndex
) -> None:
    from arasaac_mcp.vector import build_filter as bf

    params = bf(tags=["x"])
    assert params.must[0].key == "tags"
    assert seeded_index.count() == 4


# -- the registered tool ---------------------------------------------------


async def test_tool_registered_and_callable(
    catalog: Catalog, patched: VectorIndex, output_dir
) -> None:
    server = create_server(catalog.icons_dir, output_dir=output_dir)
    async with Client(server) as client:
        names = {tool.name for tool in await client.list_tools()}
        assert "semantic_search_pictograms" in names
        result = await client.call_tool(
            "semantic_search_pictograms",
            {"query": "Regen weather", "limit": 3, "mode": "semantic"},
        )
    text = "\n".join(part.text for part in result.content if part.type == "text")
    assert "Regen" in text
    assert "1_Regen.png" not in text


def test_docstring_promises_words_only() -> None:
    module = _module()
    import inspect

    registered = inspect.getsource(module.register)
    assert "WORD only" in registered or "words" in registered
