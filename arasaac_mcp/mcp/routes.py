"""The HTTP route that serves rendered sheets and viewed icons.

Tool results reference the images by URL; hosts (e.g. the ChatGPT desktop app)
show them as web preview cards.
"""

from __future__ import annotations

from pathlib import Path

from ._deps import FastMCP, Response


def register(server: "FastMCP", output_dir: Path | None) -> None:
    """Register ``GET /sheet/{name}`` on ``server``.

    Only files directly inside ``output_dir`` are served; ``output_dir`` may be
    ``None`` (no saving), in which case every request is a 404.
    """

    @server.custom_route("/sheet/{name}", methods=["GET"])
    async def sheet_file(request) -> Response:
        """Serve a rendered sheet PNG by name."""
        if output_dir is None:
            return Response(status_code=404)
        name = request.path_params["name"]
        path = (output_dir / name).resolve()
        if path.parent != output_dir.resolve() or not path.is_file():
            return Response(status_code=404)
        return Response(content=path.read_bytes(), media_type="image/png")
