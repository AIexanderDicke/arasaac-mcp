"""The ``view_pictogram`` tool: show one pictogram for visual verification."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..catalog import Catalog
from ._deps import FastMCP
from .context import ServerContext, public_base_url
from .media import image_from_path, save_icon, text


def view(catalog: Catalog, word: str, output_dir: Path | None) -> list[Any]:
    """Return a pictogram (plus its label) identified by word.

    With ``output_dir`` set the icon is saved and served under ``/sheet/`` —
    the result is text-only with an ``Image:`` URL line.  Hosts like ChatGPT
    dump image content blocks as raw JSON into the conversation, and strip
    them before the model sees them, so the URL is the useful channel there.
    Without saving (``--no-save``) the image block is returned directly for
    hosts that pass images to the model.
    """
    pic = catalog.resolve(word)
    synonyms = ", ".join(pic.keywords[1:])
    label = catalog.label_of(pic)
    caption = f'Show "{label}"' + (f" (synonyms: {synonyms})" if synonyms else "")
    if output_dir is None:
        return [text(caption), image_from_path(catalog.icons_dir / pic.file)]
    path = save_icon(catalog.icons_dir / pic.file, output_dir)
    url = f"{public_base_url()}/sheet/{path.name}"
    return [text(caption), text(f"Image: {url}")]


def register(server: "FastMCP", context: ServerContext) -> None:
    """Register ``view_pictogram`` on ``server``."""

    @server.tool
    def view_pictogram(word: str) -> list[Any]:
        """Return the image of a pictogram, identified by WORD.

        Use it to check what a candidate actually depicts before selecting it —
        ARASAAC words can mislead (e.g. `verbleiben`, `vor`).

        Gib die Bild-URL in deiner Antwort als reinen Link aus ([Piktogramm](URL)
        oder Klartext) — NIE als Markdown-Bild (![...]): eingebettete Bilder
        werden über einen Proxy geladen, der localhost nicht erreicht.
        """
        return view(context.catalog, word, context.output_dir)
