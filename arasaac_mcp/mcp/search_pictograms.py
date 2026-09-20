"""The ``search_pictograms`` tool: German word search over descriptions + metadata."""

from __future__ import annotations

from ..catalog import Catalog
from ._deps import FastMCP
from .context import ServerContext


def search(catalog: Catalog, query: str, limit: int = 25) -> str:
    """Search the pictogram library and return word-only result lines."""
    if not query.strip():
        return "Leere Suchanfrage."
    lines = catalog.search_lines(query, limit)
    if not lines:
        return (
            f'Keine Piktogramme zu "{query}" gefunden. '
            "Probiere ein Synonym oder ein einfacheres Substantiv."
        )
    return f'Gefunden: {len(lines)} Treffer für "{query}":\n' + "\n".join(lines)


def register(server: "FastMCP", context: ServerContext) -> None:
    """Register ``search_pictograms`` on ``server``."""

    @server.tool
    def search_pictograms(query: str, limit: int = 25) -> str:
        """Search ARASAAC pictograms by German keyword.

        Searches descriptions plus the official metadata (synonyms, tags,
        categories). Returns pictograms by WORD only, never by file name or id.
        Call it per concept and try synonyms when the first search is weak.
        """
        return search(context.catalog, query, limit)
