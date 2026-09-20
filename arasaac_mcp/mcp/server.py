"""Build and run the ARASAAC pictogram MCP server.

The server owns the *word contract*: tools accept German words, never ids or
file names, and ``catalog`` resolves them.  It runs **no LLM** — the host
brings the model.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from ..catalog import default_icons_dir, get_catalog
from ._deps import FastMCP
from .context import ServerContext, default_output_dir
from .instructions import INSTRUCTIONS
from .render_pictogram_layout import register as register_render_layout
from .render_pictogram_sheet import register as register_render_sheet
from .resources import register as register_resources
from .routes import register as register_routes
from .search_pictograms import register as register_search
from .view_pictogram import register as register_view


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
    catalog = get_catalog(icons_dir)
    debug_dir = (default_output_dir() if output_dir is None else Path(output_dir)) if save else None
    server = FastMCP(name="arasaac-mcp", instructions=INSTRUCTIONS)
    context = ServerContext(catalog=catalog, output_dir=debug_dir)

    register_search(server, context)
    register_view(server, context)
    register_render_sheet(server, context)
    register_render_layout(server, context)
    register_routes(server, debug_dir)
    register_resources(server)

    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arasaac-mcp",
        description="Run the ARASAAC pictogram MCP server.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "sse"],
        default=os.environ.get("ARASAAC_TRANSPORT", "stdio"),
        help="MCP transport (default: ARASAAC_TRANSPORT or stdio).",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("ARASAAC_HOST", "127.0.0.1"),
        help="Host for http/sse (default: ARASAAC_HOST or 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("ARASAAC_PORT", "8000")),
        help="Port for http/sse (default: ARASAAC_PORT or 8000).",
    )
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
