"""The ``search_pictograms`` tool: German word search over descriptions + metadata."""

from __future__ import annotations

from ..catalog import Catalog
from ._deps import FastMCP
from .context import ServerContext


def search(catalog: Catalog, query: str, limit: int = 25) -> str:
    """Search the pictogram library and return word-only result lines."""
    if not query.strip():
        return "Empty search query."
    lines = catalog.search_lines(query, limit)
    if not lines:
        return f'No pictograms found for "{query}". Try a synonym or a simpler noun.'
    return f'Found: {len(lines)} matches for "{query}":\n' + "\n".join(lines)


def register(server: FastMCP, context: ServerContext) -> None:
    """Register ``search_pictograms`` on ``server``."""

    @server.tool
    def search_pictograms(query: str, limit: int = 25) -> str:
        """Search ARASAAC pictograms by German keyword.

        Retrieval comes from the word layer only: the rich, model-written icon
        descriptions (description, usage, synonyms) plus the official metadata
        (German keywords, tags, categories).  The pictogram images themselves
        are never a source of information — they are only fetched by id for
        the final display. Returns pictograms by WORD only, never by file name
        or id.  Call it per concept and try synonyms when the first search is
        weak.
        """
        return search(context.catalog, query, limit)
