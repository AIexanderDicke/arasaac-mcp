"""The ``render_pictogram_layout`` tool: free layout tree (grid/cards/canvas)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..catalog import Catalog
from ..layout import SheetOptions, render_layout
from ._deps import FastMCP, ToolResult
from .context import ServerContext
from .media import png_bytes, render_result, save_png


def render_tree(
    catalog: Catalog,
    layout: dict[str, Any],
    sentence: str | None = None,
    meaning: str | None = None,
    page_size: str | None = None,
    labels: bool = True,
    icon_size: int | None = None,
    output_dir: Path | None = None,
) -> ToolResult:
    """Render a free layout tree (grid/cards/canvas) of pictogram words."""
    if not isinstance(layout, dict):
        raise ValueError("layout must be a layout object")
    tree = catalog.resolve_layout_node(layout)
    spec = {"sentence": sentence, "meaning": meaning, "layout": tree}
    options = SheetOptions(
        labels=labels,
        page_size=page_size,
        sentence=sentence,
        meaning=meaning,
        **({"icon_size": icon_size} if icon_size else {}),
    )
    image = render_layout(spec, options, icons_dir=catalog.icons_dir)
    lines = ["Rendered pictogram layout"]
    saved = save_png(image, output_dir)
    if saved is not None:
        lines.append(f"File: {saved}")
    return render_result(lines, png_bytes(image), saved)


def register(server: "FastMCP", context: ServerContext) -> None:
    """Register ``render_pictogram_layout`` on ``server``."""

    @server.tool
    def render_pictogram_layout(
        layout: dict[str, Any],
        sentence: str | None = None,
        meaning: str | None = None,
        page_size: str | None = None,
        labels: bool = True,
        icon_size: int | None = None,
    ) -> ToolResult:
        """Render a free arrangement of pictogram WORDS as an image.

        For timetables/tables (`grid` with `columns` and `rows`), cards with
        `arrow` connectors, or free placement (`canvas`). Icon nodes name a
        `word` (e.g. {"type": "icon", "word": "Mathe", "role": "NOUN"}); a bare
        string is an icon shorthand and a list becomes a column. Node types:
        icon, text, row, column, card, grid, arrow, spacer, divider, canvas.

        Gib die Bild-URL in deiner Antwort als reinen Link aus
        ([Piktogrammblatt](URL) oder Klartext) — NIE als Markdown-Bild
        (![...]): der Host erzeugt daraus die Web-Vorschau, und eingebettete
        Bilder werden über einen Proxy geladen, der localhost nicht erreicht.
        """
        return render_tree(
            context.catalog,
            layout,
            sentence,
            meaning,
            page_size,
            labels,
            icon_size,
            context.output_dir,
        )
