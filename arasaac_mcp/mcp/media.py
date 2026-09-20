"""Content and file helpers shared by the tools.

Image delivery
--------------
The picture is **not** inlined in the tool result.  Hosts either drop image
blocks or dump the base64 into the conversation as raw text, and widget
sandboxes block inline ``data:`` images.  Instead the server keeps the PNG
(``output_dir``), exposes ``GET /sheet/<name>`` and the result carries the URL.
Hosts like the ChatGPT desktop app render that URL as a web preview card.

The image content block survives only for the ``--no-save`` case, for hosts
that pass images to the model.
"""

from __future__ import annotations

import io
import secrets
import time
from pathlib import Path
from typing import Any

from ._deps import McpImage, TextContent, ToolResult
from .context import public_base_url


def text(value: str) -> Any:
    """A plain text content block."""
    return TextContent(type="text", text=value)


def image_from_bytes(data: bytes) -> Any:
    """A PNG image content block from raw bytes."""
    return McpImage(data=data, format="png")


def png_bytes(image: Any) -> bytes:
    """Serialise a Pillow image to PNG bytes."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def image_from_path(path: Path) -> Any:
    """A PNG image content block read from a file."""
    return image_from_bytes(path.read_bytes())


def save_png(image: Any, output_dir: Path | None) -> Path | None:
    """Persist a rendered sheet locally for debugging.  ``None`` disables it."""
    if output_dir is None:
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"sheet_{int(time.time() * 1000)}-{secrets.token_hex(2)}.png"
    image.save(path, format="PNG")
    return path


def save_icon(icon_path: Path, output_dir: Path) -> Path:
    """Copy an icon into ``output_dir`` so it can be served under ``/sheet/``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"icon_{int(time.time() * 1000)}-{secrets.token_hex(2)}-{icon_path.name}"
    path.write_bytes(icon_path.read_bytes())
    return path


def render_result(lines: list[str], png: bytes, saved: Path | None) -> "ToolResult":
    """Build the tool result for a rendered sheet.

    When the PNG was saved, its ``/sheet/<name>`` URL is appended to ``lines``
    and the result is text-only.  No ``structuredContent``: hosts dump it as
    raw JSON into the conversation.  Without a saved file (``--no-save``) the
    image still travels as an image content block for the model.
    """
    if saved is not None:
        url = f"{public_base_url()}/sheet/{saved.name}"
        lines.append(f"Bild: {url}")
        return ToolResult(content=[text("\n".join(lines))])
    return ToolResult(content=[text("\n".join(lines)), image_from_bytes(png)])
