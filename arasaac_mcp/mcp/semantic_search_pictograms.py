"""The ``semantic_search_pictograms`` tool: vector search over the icon
descriptions in Qdrant."""

from __future__ import annotations

from ..catalog import Catalog
from ..embeddings import Embedder, EmbeddingError, make_embedder
from ..vector import (
    PicMatch,
    VectorDBError,
    VectorIndex,
    build_filter,
    get_vector_index,
)
from ._deps import FastMCP
from .context import ServerContext

# Dense and hybrid scores are both normalised to roughly 0-1 (`_rrf_fuse`
# scales the reciprocal-rank fusion), so one boost weight serves both.
_BOOST_WEIGHT = 0.05


def search(
    catalog: Catalog,
    index: VectorIndex,
    embedder: Embedder,
    query: str,
    limit: int = 12,
    mode: str = "semantic",
    boost: bool = False,
    min_score: float = 0.2,
    tags: str = "",
    categories: str = "",
) -> str:
    """Search the vector database and return word-only result lines.

    ``tags``/``categories`` are comma-separated payload filters.  The returned
    labels resolve back through :meth:`Catalog.resolve` — never ids or file
    names.
    """
    if not query.strip():
        return "Empty search query."
    if mode not in {"semantic", "synonyms", "hybrid"}:
        return f"Unknown search mode {mode!r} (semantic|synonyms|hybrid)."
    try:
        text_vector = embedder.embed([query], is_query=True)[0]
        # One query vector serves both prefetches in hybrid mode; the same
        # request text is matched against either vector space.
        syn_vector = text_vector if mode == "hybrid" else None
        filters = build_filter(tags=_split(tags), categories=_split(categories))
        matches = index.search(
            text_vector,
            mode=mode,
            limit=limit,
            filters=filters,
            boost=boost,
            boost_weight=_BOOST_WEIGHT,
            query_text=query,
            syn_vector=syn_vector,
            min_score=min_score,
        )
    except (VectorDBError, EmbeddingError) as exc:
        return f"Semantic search failed: {exc}"
    lines = _format(catalog, matches)
    if not lines:
        return (
            f'No pictograms found for "{query}". '
            "Try a synonym or a simpler word, or use search_pictograms."
        )
    return f'Found: {len(lines)} matches for "{query}":\n' + "\n".join(lines)


def _split(values: str) -> list[str] | None:
    parts = [value.strip() for value in values.split(",") if value.strip()]
    return parts or None


def _format(catalog: Catalog, matches: list[PicMatch]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for position, match in enumerate(matches, start=1):
        pic = catalog.by_id(match.pic_id)
        if pic is None:
            continue
        label = catalog.label_of(pic)
        if label.lower() in seen:
            continue
        seen.add(label.lower())
        description = str(match.payload.get("description") or "").strip()
        detail = ""
        if description:
            detail = f" — {description[:160]}"
        lines.append(f"{position}. {label}{detail}")
    return lines


def _index_for(context: ServerContext) -> VectorIndex:
    """The env-configured vector index (built lazily, reused per process)."""
    return get_vector_index()


def _embedder_for() -> Embedder:
    return make_embedder()


def register(server: FastMCP, context: ServerContext) -> None:
    """Register ``semantic_search_pictograms`` on ``server``."""

    @server.tool
    def semantic_search_pictograms(
        query: str,
        limit: int = 12,
        mode: str = "semantic",
        boost: bool = False,
        min_score: float = 0.2,
        tags: str = "",
        categories: str = "",
    ) -> str:
        """Find ARASAAC pictograms semantically, from a natural request.

        Embeds the request (German sentences work fine against the English
        description index) and searches the Qdrant vector database.
        ``mode``: ``semantic`` (descriptions + usage), ``synonyms``
        (synonyms/keywords), ``hybrid`` (both, rank-fused).
        ``boost`` re-ranks hits whose tags/categories/keywords/synonyms match
        query words; ``min_score`` drops weak neighbors (cosine threshold);
        ``tags``/``categories`` filter (comma-separated).
        Returns pictograms by WORD only, never ids or file names; the labels
        resolve back to the same pictograms.  Falls back gracefully with a
        message when the vector database is not running.
        """
        return search(
            context.catalog,
            _index_for(context),
            _embedder_for(),
            query,
            limit=limit,
            mode=mode,
            boost=boost,
            min_score=min_score,
            tags=tags,
            categories=categories,
        )
