"""The Qdrant vector layer (:mod:`arasaac_mcp.vector`), fully offline.

Qdrant's in-process local mode (``QdrantClient(":memory:")``) replaces the
Docker container; the deterministic :class:`HashingEmbedder` replaces a real
embedding model.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers import HashingEmbedder
from qdrant_client import QdrantClient

from arasaac_mcp.vector import (
    DEFAULT_COLLECTION,
    PicRecord,
    VectorDBError,
    VectorIndex,
    apply_boost,
    build_filter,
    tokenize,
)

pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect in the local Qdrant")

DIM = HashingEmbedder.DIM


def make_record(
    pic_id: int,
    word: str,
    description: str,
    *,
    usage: str = "",
    synonyms: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
) -> PicRecord:
    return PicRecord(
        pic_id=pic_id,
        label=word,
        word=word,
        file_stem=f"{pic_id}_{word}.png",
        description=description,
        usage=usage,
        synonyms=synonyms,
        keywords=(word,),
        tags=tags,
        categories=(),
    )


@pytest.fixture
def index() -> VectorIndex:
    client = QdrantClient(":memory:")
    index = VectorIndex(client, "test_col")
    index.ensure_collection(DIM)
    return index


def seed(index: VectorIndex, *records: PicRecord) -> None:
    embedder = HashingEmbedder()
    text = embedder.embed([r.text_document() for r in records])
    syn = embedder.embed([r.syn_document() for r in records])
    index.upsert(records, [{"text": a, "syn": b} for a, b in zip(text, syn, strict=True)])


# -- tokenize ------------------------------------------------------------


def test_tokenize_mirrors_catalog() -> None:
    assert tokenize("Rotes Auto-Fahren!") == ["rotes", "auto", "fahren"]
    assert tokenize("") == []


# -- PicRecord documents -------------------------------------------------


def test_text_document_uses_description_and_usage() -> None:
    record = make_record(1, "dog", "A dog.", usage="Use for dogs.")
    assert record.text_document() == "A dog. Use for dogs."
    assert record.syn_document() == "dog"


def test_syn_document_joins_synonyms_and_keywords() -> None:
    record = make_record(2, "Hund", "A dog.", synonyms=("dog", "canine"), tags=("animal", "work"))
    assert record.syn_document() == "dog, canine, Hund, animal, work"


def test_payload_shape(index: VectorIndex) -> None:
    record = make_record(3, "Katze", "A cat.")
    seed(index, record)
    stored = index._dense([0.0] * DIM, "text", 1, None)
    payload = stored[0].payload
    assert payload["id"] == 3
    assert payload["label"] == "Katze"
    assert payload["keywords"] == ["Katze"]
    assert payload["synonyms"] == []
    assert payload["tags"] == []


# -- collection schema ---------------------------------------------------


def test_dimension_and_ids(index: VectorIndex) -> None:
    assert index.dimension() == DIM
    assert not index.existing_ids()
    seed(
        index,
        make_record(11, "Regen", "Rain falls from clouds.", usage="Weather."),
        make_record(12, "Schirm", "An umbrella.", usage="Protection."),
    )
    assert index.count() == 2
    assert index.existing_ids() == {11, 12}


def test_dimension_mismatch_rejected(index: VectorIndex) -> None:
    with pytest.raises(VectorDBError, match="--recreate"):
        index.ensure_collection(DIM + 1)


def test_ensure_collection_on_empty_index() -> None:
    index = VectorIndex(QdrantClient(":memory:"), "fresh_col")
    assert index.ensure_collection(DIM) is True
    assert index.ensure_collection(DIM) is False
    assert index.collection_exists()


def test_recreate_clears_points(index: VectorIndex) -> None:
    seed(index, make_record(21, "auto", "A red car."))
    assert index.count() == 1
    index.ensure_collection(DIM, recreate=True)
    assert index.count() == 0


# -- search --------------------------------------------------------------


def test_semantic_search_finds_similar(index: VectorIndex) -> None:
    seed(
        index,
        make_record(
            31, "Hund", "A dog runs across the meadow.", usage="Domestic animal.", tags=("animal",)
        ),
        make_record(32, "Auto", "A red car drives on the road.", usage="Vehicle."),
        make_record(33, "Katze", "A cat sleeps on a cushion.", usage="Domestic animal."),
    )
    q = HashingEmbedder().embed(["A dog runs across the meadow"], is_query=True)[0]
    hits = index.search(q, mode="semantic", limit=2)
    assert [hit.pic_id for hit in hits] == [31, 33]
    assert all(hit.payload["description"] for hit in hits)


def test_synonyms_mode(index: VectorIndex) -> None:
    seed(
        index,
        make_record(41, "Hund", "An animal.", synonyms=("dog", "canine")),
        make_record(42, "Auto", "A vehicle.", synonyms=("car", "vehicle")),
    )
    q = HashingEmbedder().embed(["dog"], is_query=True)[0]
    hits = index.search(q, mode="synonyms", limit=2)
    assert next(hit.pic_id for hit in hits) == 41


def test_hybrid_mode_fuses(index: VectorIndex) -> None:
    seed(
        index,
        make_record(51, "Hund", "Dog runs meadow.", synonyms=("dog", "canine")),
        make_record(52, "Auto", "Red car road.", synonyms=("car",)),
    )
    vectors = HashingEmbedder().embed(["dog"], is_query=True)
    hits = index.search(
        vectors[0],
        mode="hybrid",
        limit=2,
        syn_vector=vectors[0],
    )
    assert hits[0].pic_id == 51
    assert {hit.pic_id for hit in hits} == {51, 52}


def test_hybrid_needs_syn_vector(index: VectorIndex) -> None:
    with pytest.raises(ValueError, match="syn_vector"):
        index.search([0.0] * DIM, mode="hybrid", limit=1)


def test_unknown_mode_rejected(index: VectorIndex) -> None:
    with pytest.raises(ValueError, match="mode"):
        index.search([0.0] * DIM, mode="quantum")


def test_search_is_deterministic(index: VectorIndex) -> None:
    seed(
        index,
        make_record(61, "a", "Shared sentence about weather.", synonyms=("x",)),
        make_record(62, "b", "Shared sentence about weather.", synonyms=("x",)),
        make_record(63, "c", "Shared sentence about weather.", synonyms=("x",)),
    )
    q = HashingEmbedder().embed(["Shared sentence about weather"], is_query=True)[0]
    first = [hit.pic_id for hit in index.search(q, limit=3)]
    second = [hit.pic_id for hit in index.search(q, limit=3)]
    assert first == second


def test_filters_narrow(index: VectorIndex) -> None:
    seed(
        index,
        make_record(71, "Regen", "Rain.", tags=("wetter",)),
        make_record(72, "Auto", "Car.", tags=("fahrzeug",)),
    )
    q = HashingEmbedder().embed(["rain drop"], is_query=True)[0]
    unfiltered = index.search(q, limit=5)
    assert next(hit.pic_id for hit in unfiltered) == 71
    filtered = index.search(
        q,
        limit=5,
        filters=build_filter(tags=["fahrzeug"]),
    )
    assert [hit.pic_id for hit in filtered] == [72]
    everything = index.search(
        q,
        limit=5,
        filters=build_filter(tags=["wetter", "fahrzeug"]),
    )
    assert {hit.pic_id for hit in everything} == {71, 72}


def test_boost_promotes_tag_match(index: VectorIndex) -> None:
    seed(
        index,
        make_record(
            81, "Vogel", "A friendly animal drawing.", synonyms=("sparrow",), tags=("bird",)
        ),
        make_record(82, "Hund", "A friendly animal drawing.", synonyms=("dog",), tags=("dog",)),
    )
    # Identical documents tie on cosine similarity; the tag/keyword boost then
    # has to put the record whose payload matches the query text first.
    q = HashingEmbedder().embed(["friendly animal drawing"], is_query=True)[0]
    boosted = index.search(q, limit=2, boost=True, query_text="dog")
    assert boosted[0].pic_id == 82
    # Without the boost text there is nothing to match and nothing changes.
    untouched = index.search(q, limit=2, boost=True, query_text="sparrow")
    assert untouched[0].pic_id != 82


def test_apply_boost_without_matching_tokens_keeps_scores(index: VectorIndex) -> None:
    seed(
        index,
        make_record(85, "Fahrrad", "drawing of a bike", synonyms=("cycle",)),
        make_record(86, "Rad", "drawing of a bike", synonyms=("wheel",)),
    )
    q = HashingEmbedder().embed(["bike"], is_query=True)[0]
    matches = index.search(q, limit=2)
    reapplied = apply_boost(matches, "completely different words")

    def order(matches_list):
        return sorted(((m.score, m.pic_id) for m in matches_list), reverse=True)

    assert order(reapplied) == order(matches)
    assert {m.pic_id for m in reapplied} == {85, 86}


def test_boost_weight_changes_margin(index: VectorIndex) -> None:
    seed(
        index,
        make_record(83, "a", "drawing of a bike", synonyms=("cycle",)),
        make_record(84, "b", "drawing of a bike", synonyms=("bike", "rad")),
    )
    q = HashingEmbedder().embed(["bike"], is_query=True)[0]
    assert apply_boost(index.search(q, limit=2), "bike rad")[0].score > (
        apply_boost(index.search(q, limit=2), "unrelated string")[0].score
    )


# -- misc ----------------------------------------------------------------


def test_search_empty_index_returns_nothing(index: VectorIndex) -> None:
    q = HashingEmbedder().embed(["dog"], is_query=True)[0]
    assert index.search(q, limit=3) == []


def test_upsert_length_mismatch(index: VectorIndex) -> None:
    with pytest.raises(ValueError, match="same length"):
        index.upsert([make_record(1, "x", "y")], [{"text": [0.0], "syn": [0.0]}] * 2)


def test_default_collection_name() -> None:
    assert DEFAULT_COLLECTION == "arasaac_en"


def test_indexes_survive_reopen(tmp_path: Path) -> None:
    client = QdrantClient(":memory:")
    index = VectorIndex(client, "tmp_col")
    index.ensure_collection(DIM)
    seed(index, make_record(91, "wolf", "A wolf howls at the full moon."))
    again = VectorIndex(client, "tmp_col")
    assert again.count() == 1
    assert again.existing_ids() == {91}
