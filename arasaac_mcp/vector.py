"""Qdrant-backed vector search over the LLM icon descriptions.

The collection holds one point per pictogram (point id = ARASAAC pic id) with
two named vectors and a rich payload:

- ``text`` — embedding of ``description + usage`` (the semantic document)
- ``syn`` — embedding of ``synonyms + German keywords`` (the synonym option)
- payload — ``label``, ``word``, ``keywords``, ``synonyms``, ``tags``,
  ``categories`` plus the description fields; ``tags``/``categories``/``keywords``/
  ``synonyms`` carry payload indexes so they can filter (and thereby boost) a
  search.

Search modes (see :meth:`VectorIndex.search`): ``semantic`` (text vector),
``synonyms`` (syn vector) and ``hybrid`` (reciprocal-rank fusion of both).
The module is network-capable only through the Qdrant client; the word layer in
:mod:`arasaac_mcp.catalog` stays untouched and network-free.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any, cast

from qdrant_client import QdrantClient, models

DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
DEFAULT_COLLECTION = "arasaac_en"

#: Name of the description/usage vector and of the synonym vector.
TEXT_VECTOR = "text"
SYN_VECTOR = "syn"

#: Payload fields that get a keyword payload index (filterable).
PAYLOAD_INDEX_FIELDS: tuple[str, ...] = ("keywords", "tags", "categories", "synonyms")

_TOKEN_RE = re.compile(r"[^\W_]+")


class VectorDBError(RuntimeError):
    """Qdrant is unreachable, misconfigured or returned an unusable answer."""


def tokenize(text: str) -> list[str]:
    """Lower-cased word tokens, mirroring the catalog's query segmentation."""
    return _TOKEN_RE.findall(text.lower())


def qdrant_url() -> str:
    """Qdrant REST URL (``ARASAAC_QDRANT_URL``, default ``http://127.0.0.1:6333``)."""
    return os.environ.get("ARASAAC_QDRANT_URL", DEFAULT_QDRANT_URL).rstrip("/")


def collection_name() -> str:
    """Collection with the pictogram vectors (``ARASAAC_QDRANT_COLLECTION``,
    default ``arasaac_en``)."""
    return os.environ.get("ARASAAC_QDRANT_COLLECTION", DEFAULT_COLLECTION)


#: Open indexes per (url, collection) so MCP tools reuse one client.
_INDEX_CACHE: dict[tuple[str, str], VectorIndex] = {}


def get_vector_index(url: str | None = None, collection: str | None = None) -> VectorIndex:
    """A cached :class:`VectorIndex` for the given (or env-configured) target."""
    key = (url or qdrant_url(), collection or collection_name())
    index = _INDEX_CACHE.get(key)
    if index is None:
        index = VectorIndex.open(*key)
        _INDEX_CACHE[key] = index
    return index


@dataclass(frozen=True)
class PicRecord:
    """Everything one pictogram contributes to the vector index."""

    pic_id: int
    label: str
    word: str
    description: str
    usage: str
    synonyms: tuple[str, ...]
    keywords: tuple[str, ...]
    tags: tuple[str, ...]
    categories: tuple[str, ...]

    def text_document(self) -> str:
        """What the ``text`` vector embeds: description and usage."""
        return " ".join(part for part in (self.description, self.usage) if part)

    def syn_document(self) -> str:
        """What the ``syn`` vector embeds: synonyms and German keywords."""
        return ", ".join(part for part in (*self.synonyms, *self.keywords, *self.tags) if part)

    def payload(self) -> dict[str, object]:
        return {
            "id": self.pic_id,
            "label": self.label,
            "word": self.word,
            "description": self.description,
            "usage": self.usage,
            "synonyms": list(self.synonyms),
            "keywords": list(self.keywords),
            "tags": list(self.tags),
            "categories": list(self.categories),
        }


@dataclass(frozen=True)
class PicMatch:
    """One search hit: pic id, score and the stored payload."""

    pic_id: int
    score: float
    payload: dict[str, object]


def build_filter(
    *,
    tags: list[str] | None = None,
    categories: list[str] | None = None,
    keywords: list[str] | None = None,
) -> models.Filter | None:
    """A Qdrant filter over the payload indexes, or ``None`` for no filtering.

    Values within one field are ORed; the fields are ANDed.
    """
    conditions: list[models.FieldCondition] = []
    for key, values in (("tags", tags), ("categories", categories), ("keywords", keywords)):
        cleaned = [value.strip() for value in values or [] if value.strip()]
        if cleaned:
            conditions.append(models.FieldCondition(key=key, match=models.MatchAny(any=cleaned)))
    if not conditions:
        return None
    return models.Filter(
        must=cast(
            "list[models.FieldCondition | models.IsEmptyCondition | models.IsNullCondition | models.HasIdCondition | models.HasVectorCondition | models.SliceCondition | models.NestedCondition | models.Filter]",
            conditions,
        )
    )


def _wrap(call: Callable[[], Any], url: str, collection: str, action: str) -> Any:
    """Run ``call``, re-raising Qdrant client errors as :class:`VectorDBError`."""
    try:
        return call()
    except VectorDBError:
        raise
    except Exception as exc:  # qdrant-client raises httpx/grpc errors
        raise VectorDBError(
            f"Qdrant {action} failed (url={url}, collection={collection}): {exc} "
            "(start the database with: docker compose up -d qdrant)"
        ) from exc


class VectorIndex:
    """Vector search over one Qdrant collection of pictogram records."""

    def __init__(self, client: QdrantClient, collection: str = DEFAULT_COLLECTION) -> None:
        self.client = client
        self.collection = collection
        self._url = qdrant_url()

    @classmethod
    def open(cls, url: str | None = None, collection: str | None = None) -> VectorIndex:
        """Open the collection at ``url`` (``ARASAAC_QDRANT_URL``)."""
        return cls(QdrantClient(url or qdrant_url(), timeout=10), collection or collection_name())

    # -- schema ------------------------------------------------------------

    def collection_exists(self) -> bool:
        exists = _wrap(
            partial(self.client.collection_exists, self.collection),
            self._url,
            self.collection,
            "collection_exists",
        )
        return bool(exists)

    def dimension(self) -> int | None:
        """The stored vector dimension, or ``None`` when there is none yet."""
        info = _wrap(
            partial(self.client.get_collection, self.collection),
            self._url,
            self.collection,
            "get_collection",
        )
        vectors = info.config.params.vectors
        if isinstance(vectors, models.VectorParams):
            return int(vectors.size)
        if isinstance(vectors, dict) and vectors:
            first = next(iter(vectors.values()))
            if isinstance(first, models.VectorParams):
                return int(first.size)
        return None

    def ensure_collection(self, dim: int, *, recreate: bool = False) -> bool:
        """Create the collection (and payload indexes) if needed.

        Returns ``True`` when a fresh collection was created.  With
        ``recreate`` an existing collection is dropped first.  An existing
        collection with a different dimension raises :class:`VectorDBError`.
        """
        if self.collection_exists():
            if recreate:
                _wrap(
                    partial(self.client.delete_collection, self.collection),
                    self._url,
                    self.collection,
                    "delete_collection",
                )
            else:
                existing = self.dimension()
                if existing is not None and existing != dim:
                    raise VectorDBError(
                        f"collection {self.collection!r} has dimension {existing}, "
                        f"but the embedding model produces {dim}; "
                        "re-ingest with --recreate (or use a fresh --collection)"
                    )
                return False
        params = models.VectorParams(size=dim, distance=models.Distance.COSINE)
        _wrap(
            partial(
                self.client.create_collection,
                self.collection,
                vectors_config={TEXT_VECTOR: params, SYN_VECTOR: params},
            ),
            self._url,
            self.collection,
            "create_collection",
        )
        for field in PAYLOAD_INDEX_FIELDS:
            _wrap(
                partial(
                    self.client.create_payload_index,
                    self.collection,
                    field,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                ),
                self._url,
                self.collection,
                "create_payload_index",
            )
        return True

    # -- writing -----------------------------------------------------------

    def count(self) -> int:
        result = _wrap(
            partial(self.client.count, self.collection),
            self._url,
            self.collection,
            "count",
        )
        return int(result.count)

    def existing_ids(self) -> set[int]:
        """Every point id currently stored (for resumable ingestion)."""
        ids: set[int] = set()
        offset: models.ExtendedPointId | None = None
        while True:
            points, offset = _wrap(
                partial(
                    self.client.scroll,
                    self.collection,
                    limit=256,
                    with_payload=False,
                    with_vectors=False,
                    offset=offset,
                ),
                self._url,
                self.collection,
                "scroll",
            )
            ids.update(int(point.id) for point in points)
            if offset is None:
                return ids

    def upsert(
        self,
        records: list[PicRecord],
        vectors: list[dict[str, list[float]]],
        *,
        batch: int = 128,
    ) -> int:
        """Upsert ``records`` with per-record ``{vector_name: vector}`` maps."""
        if len(records) != len(vectors):
            raise ValueError("records and vectors must have the same length")
        written = 0
        for start in range(0, len(records), batch):
            points = [
                models.PointStruct(
                    id=record.pic_id,
                    vector={"text": map_["text"], "syn": map_["syn"]},
                    payload=record.payload(),
                )
                for record, map_ in zip(
                    records[start : start + batch],
                    vectors[start : start + batch],
                    strict=True,
                )
            ]
            _wrap(
                partial(
                    self.client.upsert,
                    self.collection,
                    points=points,
                    wait=True,
                ),
                self._url,
                self.collection,
                "upsert",
            )
            written += len(points)
        return written

    def overwrite_payload(self, records: list[PicRecord], *, batch: int = 256) -> int:
        """Replace the whole payload of stored points — without re-embedding.

        Used when the retrieval corpus changes (e.g. dropping filename data):
        vectors stay untouched, only the indexed payload is rewritten.  One
        server call per record because payloads differ per point.
        """
        changed = 0
        for record in records:
            _wrap(
                partial(
                    self.client.overwrite_payload,
                    self.collection,
                    payload=record.payload(),
                    points=[record.pic_id],
                    wait=True,
                ),
                self._url,
                self.collection,
                "overwrite_payload",
            )
            changed += 1
        return changed

    # -- reading -----------------------------------------------------------

    def search(
        self,
        query_vector: list[float],
        *,
        mode: str = "semantic",
        limit: int = 10,
        filters: models.Filter | None = None,
        boost: bool = False,
        boost_weight: float = 0.05,
        query_text: str = "",
        syn_vector: list[float] | None = None,
        min_score: float = 0.0,
        overfetch: int = 3,
    ) -> list[PicMatch]:
        """Search by mode; ``semantic``/``synonyms`` are dense, ``hybrid`` fuses
        both vectors by reciprocal-rank fusion.

        ``query_text`` is the raw query; with ``boost`` the score gains
        ``boost_weight`` per payload field (keywords, synonyms, tags,
        categories) matching a query token — a deterministic re-rank on top of
        the vector order.
        """
        if mode == "semantic":
            matches = self._dense(query_vector, TEXT_VECTOR, limit * overfetch, filters)
        elif mode == "synonyms":
            matches = self._dense(query_vector, SYN_VECTOR, limit * overfetch, filters)
        elif mode == "hybrid":
            if syn_vector is None:
                raise ValueError("hybrid search needs syn_vector")
            text_hits = self._dense(query_vector, TEXT_VECTOR, limit * overfetch, filters)
            syn_hits = self._dense(syn_vector, SYN_VECTOR, limit * overfetch, filters)
            matches = _rrf_fuse([text_hits, syn_hits])
        else:
            raise ValueError(f"unknown search mode: {mode!r} (semantic|synonyms|hybrid)")
        matches = [match for match in matches if match.score >= min_score]
        if boost:
            matches = apply_boost(matches, query_text, weight=boost_weight)
        return matches[: max(1, limit)]

    def _dense(
        self, vector: list[float], using: str, limit: int, filters: models.Filter | None
    ) -> list[PicMatch]:
        result = _wrap(
            partial(
                self.client.query_points,
                self.collection,
                query=vector,
                using=using,
                limit=max(1, limit),
                query_filter=filters,
                with_payload=True,
            ),
            self._url,
            self.collection,
            "query_points",
        )
        return [
            PicMatch(
                pic_id=int(point.id), score=float(point.score), payload=dict(point.payload or {})
            )
            for point in result.points
        ]


def _rrf_fuse(result_lists: list[list[PicMatch]], k: int = 60) -> list[PicMatch]:
    """Reciprocal-rank fusion over several dense result lists.

    The fused score is a sum of ``1/(k + rank + 1)`` terms, normalised by the
    maximum possible fusion so hybrid scores stay comparable to dense ones
    (top-of-both-lists ≈ 1.0, and ``min_score`` keeps its meaning).
    """
    scores: dict[int, float] = {}
    payloads: dict[int, dict[str, object]] = {}
    for results in result_lists:
        for rank, match in enumerate(results):
            scores[match.pic_id] = scores.get(match.pic_id, 0.0) + 1.0 / (k + rank + 1)
            payloads.setdefault(match.pic_id, match.payload)
    scale = (k + 1) / max(1, len(result_lists))
    fused = [
        PicMatch(pic_id=pic_id, score=score * scale, payload=payloads[pic_id])
        for pic_id, score in scores.items()
    ]
    fused.sort(key=lambda match: (-match.score, match.pic_id))
    return fused


def apply_boost(matches: list[PicMatch], query: str, *, weight: float = 0.05) -> list[PicMatch]:
    """Re-rank ``matches``: ``weight`` per payload field matching a query token."""
    tokens = set(tokenize(query))
    if not tokens:
        return matches
    fields = ("keywords", "synonyms", "tags", "categories")
    ranked: list[tuple[float, int, PicMatch]] = []
    for match in matches:
        matched = 0
        for field in fields:
            field_tokens: set[str] = set()
            values = match.payload.get(field)
            if isinstance(values, (list, tuple)):
                for value in values:
                    field_tokens.update(tokenize(str(value)))
            if field_tokens & tokens:
                matched += 1
        ranked.append((match.score + weight * matched, match.pic_id, match))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [
        PicMatch(pic_id=match.pic_id, score=score, payload=match.payload)
        for score, _pic_id, match in ranked
    ]
