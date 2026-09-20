"""The ``render_pictogram_sheet`` tool: ordered words -> strip image."""

from __future__ import annotations

from pathlib import Path

from ..catalog import VALID_ROLES, Catalog
from ..layout import Entry, SheetOptions, render_sheet
from ._deps import FastMCP, ToolResult
from .context import ServerContext
from .media import png_bytes, render_result, save_png


def render_word_sheet(
    catalog: Catalog,
    words: list[str],
    roles: list[str] | None = None,
    sentence: str | None = None,
    meaning: str | None = None,
    labels: bool = True,
    columns: int | None = None,
    icon_size: int | None = None,
    output_dir: Path | None = None,
) -> ToolResult:
    """Render an ordered list of pictogram words to a strip image."""
    if not words:
        raise ValueError("words darf nicht leer sein")
    if roles is not None and len(roles) != len(words):
        raise ValueError("roles muss dieselbe Länge wie words haben")
    normalized_roles = [role.upper() for role in roles] if roles else None
    if normalized_roles:
        for role in normalized_roles:
            if role not in VALID_ROLES:
                raise ValueError(f'Ungültige Rolle "{role}" (erwartet: {", ".join(VALID_ROLES)})')

    entries = []
    for index, word in enumerate(words):
        pic = catalog.resolve(word)
        role = normalized_roles[index] if normalized_roles else None
        entries.append(Entry(catalog.icons_dir / pic.file, role, catalog.label_of(pic)))

    options = SheetOptions(
        labels=labels,
        columns=columns,
        sentence=sentence,
        meaning=meaning,
        **({"icon_size": icon_size} if icon_size else {}),
    )
    image = render_sheet(entries, options, icons_dir=catalog.icons_dir)
    rendered_words = ", ".join(catalog.label_of(catalog.resolve(word)) for word in words)
    lines = [f"Gerendertes Piktogrammblatt: {rendered_words}"]
    saved = save_png(image, output_dir)
    if saved is not None:
        lines.append(f"Datei: {saved}")
    return render_result(lines, png_bytes(image), saved)


def register(server: "FastMCP", context: ServerContext) -> None:
    """Register ``render_pictogram_sheet`` on ``server``."""

    @server.tool
    def render_pictogram_sheet(
        words: list[str],
        roles: list[str] | None = None,
        sentence: str | None = None,
        meaning: str | None = None,
        labels: bool = True,
        columns: int | None = None,
        icon_size: int | None = None,
    ) -> ToolResult:
        """Render an ordered list of pictogram WORDS to a single strip image.

        Pass the words in reading order (left→right = first … then). `roles` is
        optional and parallel to `words`: PERSON, NOUN, VERB, QUALITY, SOCIAL,
        MISC (Fitzgerald colour frames). Call it once for the primary sequence.

        Gib die Bild-URL in deiner Antwort als reinen Link aus
        ([Piktogrammblatt](URL) oder Klartext) — NIE als Markdown-Bild
        (![...]): der Host erzeugt daraus die Web-Vorschau, und eingebettete
        Bilder werden über einen Proxy geladen, der localhost nicht erreicht.
        """
        return render_word_sheet(
            context.catalog,
            words,
            roles,
            sentence,
            meaning,
            labels,
            columns,
            icon_size,
            context.output_dir,
        )
