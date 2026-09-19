"""MCP server: ARASAAC pictogram tools for any MCP-capable host.

The host brings the model.  This server only exposes the deterministic
capability — word search, visual inspection and rendering — so no API key or LLM
runs here.  The recipe (how to pick and order pictograms) ships as an MCP prompt
and as the ``arasaac-pictograms`` Agent Skill; the essential operational rules
are also in the tool descriptions, which every host puts in context.

Tools:
    search_pictograms        German word search over descriptions + metadata
    view_pictogram           return a pictogram image for visual verification
    render_pictogram_sheet   render an ordered word sequence to a strip
    render_pictogram_layout  render a free layout tree (grid/cards/canvas)

Prompts:
    pictogram_transcriber    the full recipe + the German text to transcribe

Resources:
    arasaac://skill          the Agent Skill (SKILL.md)
    arasaac://rules          the full recipe (skill + references)

Requires the optional extra: ``uv sync --extra mcp``.
"""

from __future__ import annotations

import argparse
import io
import os
import secrets
import time
from pathlib import Path
from typing import Any

try:  # optional dependency (see pyproject `[project.optional-dependencies] mcp`)
    from fastmcp import FastMCP
    from fastmcp.tools import ToolResult
    from fastmcp.utilities.types import Image as McpImage
    from mcp.types import TextContent
    from starlette.responses import Response
except ImportError:  # pragma: no cover - only hit without the extra
    FastMCP = None  # type: ignore[assignment]
    ToolResult = None  # type: ignore[assignment]
    McpImage = None  # type: ignore[assignment]
    TextContent = None  # type: ignore[assignment]
    Response = None  # type: ignore[assignment]

from .catalog import VALID_ROLES, Catalog, default_icons_dir, get_catalog
from .layout import Entry, SheetOptions, render_layout, render_sheet
from .skill import rules_text, skill_markdown

INSTRUCTIONS = """\
Turn German text into ARASAAC pictograms. Address pictograms by German **word**
only — the tools resolve words to images and never expose ids or file names.
Work out the core message first (a request for a picture is satisfied by
depicting its content, not the request), drop function words, choose concrete
icons, verify ambiguous candidates with view_pictogram, keep the sequence short
(aim ≤ 5, hard cap ~8) and render it once. Reply in German. See the
`pictogram_transcriber` prompt for the full rules.\
"""
# --------------------------------------------------------------------------- #
# Image delivery: served over HTTP, shown by the host as a web preview
# --------------------------------------------------------------------------- #
#
# The picture is NOT inlined in the tool result.  Hosts either drop image
# blocks or dump the base64 into the conversation as raw text, and widget
# sandboxes block inline data: images.  Instead the server keeps the PNG
# (debug_dir), exposes GET /sheet/<name>, and the result carries `image_url`.
# Hosts like the ChatGPT desktop app render that URL as a web preview card.

# Base URL under which this server is reachable.  The default matches the
# container port-forward used by the ChatGPT desktop app (host: localhost:8000).
def public_base_url() -> str:
    return os.environ.get("ARASAAC_PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")




# --------------------------------------------------------------------------- #
# Content helpers
# --------------------------------------------------------------------------- #


def _text(value: str) -> Any:
    return TextContent(type="text", text=value)


def _image_from_bytes(data: bytes) -> Any:
    return McpImage(data=data, format="png")


def _png_bytes(image: Any) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _image_from_path(path: Path) -> Any:
    return _image_from_bytes(path.read_bytes())


def _image_from_pil(image: Any) -> Any:
    return _image_from_bytes(_png_bytes(image))


def default_output_dir() -> Path:
    """Where debug renders are written (``ARASAAC_OUTPUT_DIR`` or ``./output``)."""
    env = os.environ.get("ARASAAC_OUTPUT_DIR")
    return Path(env) if env else Path.cwd() / "output"


def _save_png(image: Any, output_dir: Path | None) -> Path | None:
    """Persist a rendered sheet locally for debugging.  ``None`` disables it."""
    if output_dir is None:
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"sheet_{int(time.time() * 1000)}-{secrets.token_hex(2)}.png"
    image.save(path, format="PNG")
    return path


# --------------------------------------------------------------------------- #
# Tool implementations (plain functions, so they are testable without MCP)
# --------------------------------------------------------------------------- #


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


def view(catalog: Catalog, word: str) -> list[Any]:
    """Return a pictogram image (plus its label) identified by word."""
    pic = catalog.resolve(word)
    synonyms = ", ".join(pic.keywords[1:])
    label = catalog.label_of(pic)
    caption = f'Zeige "{label}"' + (f" (Synonyme: {synonyms})" if synonyms else "")
    return [_text(caption), _image_from_path(catalog.icons_dir / pic.file)]


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
) -> list[Any]:
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
    png = _png_bytes(image)
    lines = [f"Gerendertes Piktogrammblatt: {rendered_words}"]
    saved = _save_png(image, output_dir)
    if saved is not None:
        lines.append(f"Datei: {saved}")
    return _render_result(lines, png, saved)


def _render_result(lines: list[str], png: bytes, saved: Path | None) -> "ToolResult":
    """Build the tool result for a rendered sheet.

    The picture is not inlined: hosts either drop image blocks or dump the
    base64 as raw text into the conversation.  Instead the saved PNG is served
    under ``/sheet/<name>`` and the URL is reported in the text block; the
    host shows that URL as a web preview (from the model's reply, which is
    told to link it).  No structuredContent: hosts dump it as raw JSON into
    the conversation.  Without a saved file (``--no-save``) the image still
    travels as an image content block for the model.
    """
    if saved is not None:
        url = f"{public_base_url()}/sheet/{saved.name}"
        lines.append(f"Bild: {url}")
        return ToolResult(content=[_text("\n".join(lines))])
    return ToolResult(
        content=[_text("\n".join(lines)), _image_from_bytes(png)],
    )


def render_tree(
    catalog: Catalog,
    layout: dict[str, Any],
    sentence: str | None = None,
    meaning: str | None = None,
    page_size: str | None = None,
    labels: bool = True,
    icon_size: int | None = None,
    output_dir: Path | None = None,
) -> list[Any]:
    """Render a free layout tree (grid/cards/canvas) of pictogram words."""
    if not isinstance(layout, dict):
        raise ValueError("layout muss ein Layout-Objekt sein")
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
    png = _png_bytes(image)
    lines = ["Gerendertes Piktogramm-Layout"]
    saved = _save_png(image, output_dir)
    if saved is not None:
        lines.append(f"Datei: {saved}")
    return _render_result(lines, png, saved)


# --------------------------------------------------------------------------- #
# Server
# --------------------------------------------------------------------------- #


def create_server(
    icons_dir: Path | str | None = None,
    output_dir: Path | str | None = None,
    save: bool = True,
) -> "FastMCP":
    """Build the MCP server.

    ``icons_dir`` defaults to ``ARASAAC_ICONS_DIR``.  When ``save`` is true
    (the default), rendered sheets are also written to ``output_dir`` —
    ``ARASAAC_OUTPUT_DIR`` or ``./output`` — and served under ``/sheet/<name>``
    so the result can point the host at the image by URL.
    """
    if FastMCP is None:  # pragma: no cover - only hit without the extra
        raise SystemExit(
            "Der MCP-Server braucht das optionale Extra 'mcp'. "
            "Installiere es mit: uv sync --extra mcp"
        )

    catalog = get_catalog(icons_dir)
    debug_dir = (default_output_dir() if output_dir is None else Path(output_dir)) if save else None
    server = FastMCP(name="arasaac-pictograms", instructions=INSTRUCTIONS)

    @server.tool
    def search_pictograms(query: str, limit: int = 25) -> str:
        """Search ARASAAC pictograms by German keyword.

        Searches descriptions plus the official metadata (synonyms, tags,
        categories). Returns pictograms by WORD only, never by file name or id.
        Call it per concept and try synonyms when the first search is weak.
        """
        return search(catalog, query, limit)

    @server.tool
    def view_pictogram(word: str) -> list[Any]:
        """Return the image of a pictogram, identified by WORD.

        Use it to check what a candidate actually depicts before selecting it —
        ARASAAC words can mislead (e.g. `verbleiben`, `vor`).
        """
        return view(catalog, word)

    @server.tool
    def render_pictogram_sheet(
        words: list[str],
        roles: list[str] | None = None,
        sentence: str | None = None,
        meaning: str | None = None,
        labels: bool = True,
        columns: int | None = None,
        icon_size: int | None = None,
    ) -> "ToolResult":
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
            catalog, words, roles, sentence, meaning, labels, columns, icon_size, debug_dir
        )

    @server.tool
    def render_pictogram_layout(
        layout: dict[str, Any],
        sentence: str | None = None,
        meaning: str | None = None,
        page_size: str | None = None,
        labels: bool = True,
        icon_size: int | None = None,
    ) -> "ToolResult":
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
            catalog, layout, sentence, meaning, page_size, labels, icon_size, debug_dir
        )

    @server.custom_route("/sheet/{name}", methods=["GET"])
    async def sheet_file(request) -> "Response":
        """Serve a rendered sheet PNG by name.

        The tool results reference the PNG by URL; hosts (e.g. the ChatGPT
        desktop app) show it as a web preview card.
        """
        if debug_dir is None:
            return Response(status_code=404)
        name = request.path_params["name"]
        path = (debug_dir / name).resolve()
        if path.parent != debug_dir.resolve() or not path.is_file():
            return Response(status_code=404)
        return Response(content=path.read_bytes(), media_type="image/png")

    @server.prompt(
        name="pictogram_transcriber",
        description="The full ARASAAC transcriber recipe plus the German text to depict.",
    )
    def pictogram_transcriber(text: str) -> str:
        """Apply the pictogram recipe to a German text and depict its content."""
        return (
            f"{rules_text()}\n\n---\n\n"
            f"Transcribe the following German text into pictograms:\n\n{text}"
        )

    @server.resource(
        "arasaac://skill",
        name="arasaac-pictograms skill",
        description="The arasaac-pictograms Agent Skill (SKILL.md).",
        mime_type="text/markdown",
    )
    def skill_resource() -> str:
        """The Agent Skill definition."""
        return skill_markdown() or rules_text()

    @server.resource(
        "arasaac://rules",
        name="arasaac-pictograms rules",
        description="The full transcriber recipe (skill plus references).",
        mime_type="text/markdown",
    )
    def rules_resource() -> str:
        """The complete recipe."""
        return rules_text()

    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arasaac-mcp",
        description="Run the ARASAAC pictogram MCP server.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "sse"],
        default="stdio",
        help="MCP transport (default: stdio).",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host for http/sse.")
    parser.add_argument("--port", type=int, default=8000, help="Port for http/sse.")
    parser.add_argument(
        "--icons-dir",
        type=Path,
        default=None,
        help="Pictogram directory (default: ARASAAC_ICONS_DIR or ./icons).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Write each rendered sheet here for debugging (default: ARASAAC_OUTPUT_DIR or ./output).",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Do not write debug files; only return the image in the tool result.",
    )
    args = parser.parse_args(argv)

    icons_dir = args.icons_dir or default_icons_dir()
    if not Path(icons_dir).is_dir():
        parser.error(f"icons directory not found: {icons_dir}")

    server = create_server(icons_dir, output_dir=args.output_dir, save=not args.no_save)
    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(transport=args.transport, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
