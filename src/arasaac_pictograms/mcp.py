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
import base64
import io
import os
import secrets
import time
from pathlib import Path
from typing import Any

try:  # optional dependency (see pyproject `[project.optional-dependencies] mcp`)
    from fastmcp import FastMCP
    from fastmcp.tools import ToolResult
    from fastmcp.utilities.mime import UI_MIME_TYPE
    from fastmcp.utilities.types import Image as McpImage
    from mcp.types import TextContent
except ImportError:  # pragma: no cover - only hit without the extra
    FastMCP = None  # type: ignore[assignment]
    ToolResult = None  # type: ignore[assignment]
    UI_MIME_TYPE = None  # type: ignore[assignment]
    McpImage = None  # type: ignore[assignment]
    TextContent = None  # type: ignore[assignment]

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
# MCP Apps viewer (host-agnostic, MCP Apps extension / SEP-1865)
# --------------------------------------------------------------------------- #
#
# Hosts that support MCP Apps render this UI resource inline for the render
# tools and show the picture to the user — the plain `image` tool result only
# reaches the model.  This uses the standard `ui://` + ext-apps bridge; it is
# not tailored to any single host.

SHEET_VIEW_URI = "ui://arasaac/viewer.html"
_EXT_APPS_CDN = "https://unpkg.com"
_EXT_APPS_URL = f"{_EXT_APPS_CDN}/@modelcontextprotocol/ext-apps@1.0.1/app-with-deps"

# Metadata attached to both render tools: point the host at the viewer and
# allow it to load the bridge script.  Standard MCP Apps metadata only.
_TOOL_UI_META: dict[str, Any] = {
    "ui": {
        "resourceUri": SHEET_VIEW_URI,
        "csp": {"resourceDomains": [_EXT_APPS_CDN], "connectDomains": [_EXT_APPS_CDN]},
    },
    "ui/resourceUri": SHEET_VIEW_URI,
}

# Host-agnostic viewer.  Primary path is the standard MCP Apps bridge
# (ext-apps); if the host instead exposes the OpenAI Apps SDK compatibility
# API, that is used as a fallback.  A status line makes failures visible.
SHEET_VIEW_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="color-scheme" content="light dark">
  <title>ARASAAC Piktogramme</title>
  <style>
    :root { color-scheme: light dark; }
    html, body { margin: 0; padding: 0; background: transparent; }
    body { font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
           display: flex; justify-content: center; }
    .card { display: flex; flex-direction: column; gap: 10px; align-items: center;
            padding: 12px; max-width: 100%; }
    img { max-width: 100%; height: auto; border-radius: 10px; background: #fff;
          box-shadow: 0 2px 10px rgba(0, 0, 0, 0.12); }
    .caption { font-size: 14px; text-align: center; white-space: pre-line; }
    .download { font-size: 12px; padding: 6px 12px; border-radius: 8px;
                border: 1px solid currentColor; text-decoration: none; }
    .status { opacity: 0.55; font-size: 11px; text-align: center;
              font-family: ui-monospace, monospace; word-break: break-word; }
  </style>
</head>
<body>
  <div class="card">
    <img id="sheet" alt="Piktogrammfolge" hidden>
    <div id="caption" class="caption"></div>
    <a id="download" class="download" download="piktogramme.png" hidden>Bild herunterladen</a>
    <div id="status" class="status">viewer v7 · Skript lädt …</div>
  </div>
  <script>
    window.__arasaacStatus = function (message) {
      var el = document.getElementById("status");
      if (el) el.textContent = "viewer v7 · " + message;
    };
    window.addEventListener("error", function (e) {
      window.__arasaacStatus("Fehler: " + (e.message || e.error));
    });
    window.addEventListener("unhandledrejection", function (e) {
      window.__arasaacStatus("Promise-Fehler: " + e.reason);
    });
  </script>
  <script type="module">
    const status = window.__arasaacStatus;
    const img = document.getElementById("sheet");
    const caption = document.getElementById("caption");
    const download = document.getElementById("download");

    function show(src, text, note) {
      if (text) caption.textContent = text;
      if (!src) { status("kein Bild gefunden · " + (note || "")); return; }
      img.src = src;
      img.hidden = false;
      download.href = src;
      download.hidden = false;
      status("Bild angezeigt");
    }

    // Pull image data out of a raw string: either a full data: URI, or a bare
    // base64 blob (the host may pass the payload as text, or strip the prefix).
    function dataUriIn(s) {
      const at = s.indexOf("data:image");
      if (at !== -1) {
        let end = s.length;
        const stops = [34, 39, 92, 32, 41, 10, 44];
        for (const code of stops) {
          const i = s.indexOf(String.fromCharCode(code), at);
          if (i !== -1 && i < end) end = i;
        }
        if (end - at > 64) return s.slice(at, end);
      }
      const marker = s.indexOf("base64,");
      if (marker !== -1) {
        let end = s.length;
        for (const code of [34, 39, 92, 32, 41, 10]) {
          const i = s.indexOf(String.fromCharCode(code), marker);
          if (i !== -1 && i < end) end = i;
        }
        if (end - marker > 64) return "data:image/png;base64," + s.slice(marker + 7, end);
      }
      const bare = bareBase64(s);
      if (bare) return bare;
      return null;
    }

    // A PNG/JPEG/GIF always starts with a known base64 prefix.
    function bareBase64(s) {
      const heads = [["iVBOR", "image/png"], ["/9j/", "image/jpeg"], ["R0lGOD", "image/gif"]];
      for (const pair of heads) {
        const at = s.indexOf(pair[0]);
        if (at === -1) continue;
        let end = at;
        while (end < s.length && isBase64(s.charAt(end))) end += 1;
        if (end - at > 256) return "data:" + pair[1] + ";base64," + s.slice(at, end);
      }
      return null;
    }

    function isBase64(c) {
      return (c >= "A" && c <= "Z") || (c >= "a" && c <= "z")
        || (c >= "0" && c <= "9") || c === "+" || c === "/" || c === "=";
    }

    // Recursively search any JSON value for something that looks like an image:
    // a data: URI, or a base64 payload paired with a mime type.
    function findImage(node, seen) {
      if (typeof node === "string") {
        const uri = dataUriIn(node);
        if (uri) return uri;
        const head = node.charAt(0);
        if (head === "{" || head === "[") {
          try { return findImage(JSON.parse(node), seen); } catch (e) { return null; }
        }
        return null;
      }
      if (!node || typeof node !== "object") return null;
      if (seen.indexOf(node) !== -1) return null;
      seen.push(node);
      if (Array.isArray(node)) {
        for (let i = 0; i < node.length; i++) {
          const hit = findImage(node[i], seen);
          if (hit) return hit;
        }
        return null;
      }
      if (typeof node.image === "string" && node.image.indexOf("data:") === 0) return node.image;
      if (typeof node.data === "string" && node.data.length > 512
          && (node.type === "image" || node.mimeType || node.mime_type)) {
        const mime = node.mimeType || node.mime_type || "image/png";
        return "data:" + mime + ";base64," + node.data;
      }
      for (const key in node) {
        const hit = findImage(node[key], seen);
        if (hit) return hit;
      }
      return null;
    }

    // Short description of what we actually received, for the status line.
    function describe(node, depth) {
      depth = depth || 0;
      if (node === null) return "null";
      if (Array.isArray(node)) {
        const parts = depth < 2
          ? node.slice(0, 3).map((v) => describe(v, depth + 1))
          : [];
        return "array[" + node.length + "]" + (parts.length ? "(" + parts.join("; ") + ")" : "");
      }
      const kind = typeof node;
      if (kind === "string") return "string(" + node.length + ") " + node.slice(0, 60);
      if (kind === "object") {
        const keys = Object.keys(node);
        if (depth < 2) {
          return "object{" + keys.slice(0, 6).map((k) => k + ":" + describe(node[k], depth + 1)).join(", ") + "}";
        }
        return "object{" + keys.slice(0, 6).join(",") + "}";
      }
      return kind + "(" + String(node).slice(0, 40) + ")";
    }

    function findText(node) {
      if (node && typeof node.words === "string") return node.words;
      const blocks = (node && node.content) || [];
      return blocks.filter((b) => b && b.type === "text").map((b) => b.text)
        .join(String.fromCharCode(10));
    }

    function fromResult(payload) {
      const src = findImage(payload, []);
      show(src, findText(payload), src ? "" : describe(payload));
    }

    // 1) Standard, host-agnostic MCP Apps bridge.
    (async () => {
      status("verbinde (ext-apps) …");
      try {
        const { App } = await import("__EXT_APPS_URL__");
        const app = new App({ name: "ARASAAC Sheet Viewer", version: "2.0.0" });
        app.ontoolresult = (params) => fromResult(params);
        app.onhostcontextchanged = (ctx) => {
          const insets = ctx && ctx.safeAreaInsets;
          if (!insets) return;
          document.body.style.paddingTop = insets.top + "px";
          document.body.style.paddingRight = insets.right + "px";
          document.body.style.paddingBottom = insets.bottom + "px";
          document.body.style.paddingLeft = insets.left + "px";
        };
        await app.connect();
        status("ext-apps verbunden, warte auf Ergebnis …");
      } catch (error) {
        status("ext-apps nicht verfügbar (" + error + ")");
      }
    })();

    // 2) OpenAI Apps SDK compatibility API, if the host provides it.
    function fromOpenAI() {
      const openai = window.openai;
      if (!openai) return false;
      const output = openai.toolOutput;
      if (output && (output.image || output.words)) {
        status("window.openai Ergebnis");
        fromResult(output);
      } else {
        status("window.openai erkannt (noch kein Ergebnis)");
      }
      return true;
    }
    if (!fromOpenAI()) {
      window.addEventListener("openai:set_globals", fromOpenAI);
    }
  </script>
</body>
</html>
""".replace("__EXT_APPS_URL__", _EXT_APPS_URL)


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
    # structuredContent is what MCP Apps hosts pass to the viewer; `content` is
    # for the model. Return both so the picture is shown either way.
    return ToolResult(
        content=[_text("\n".join(lines)), _image_from_bytes(png)],
        structured_content={
            "words": rendered_words,
            "sentence": sentence,
            "meaning": meaning,
            "image": "data:image/png;base64," + base64.b64encode(png).decode(),
            "mime_type": "image/png",
        },
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
    return ToolResult(
        content=[_text("\n".join(lines)), _image_from_bytes(png)],
        structured_content={
            "sentence": sentence,
            "meaning": meaning,
            "image": "data:image/png;base64," + base64.b64encode(png).decode(),
            "mime_type": "image/png",
        },
    )


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
    ``ARASAAC_OUTPUT_DIR`` or ``./output`` — purely for local debugging; the
    image still travels in the tool result.
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

    @server.tool(meta=_TOOL_UI_META)
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
        """
        return render_word_sheet(
            catalog, words, roles, sentence, meaning, labels, columns, icon_size, debug_dir
        )

    @server.tool(meta=_TOOL_UI_META)
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
        """
        return render_tree(
            catalog, layout, sentence, meaning, page_size, labels, icon_size, debug_dir
        )

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
        SHEET_VIEW_URI,
        name="arasaac sheet viewer",
        description="MCP Apps viewer that renders the generated pictogram sheet.",
        mime_type=UI_MIME_TYPE,
        meta={"ui": {"csp": {"resourceDomains": [_EXT_APPS_CDN]}}},
    )
    def sheet_viewer() -> str:
        """The MCP Apps viewer HTML (standard ui:// resource)."""
        return SHEET_VIEW_HTML

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
