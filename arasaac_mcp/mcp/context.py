"""Shared state and environment lookups for the MCP tools."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ..catalog import Catalog


def public_base_url() -> str:
    """Base URL under which this server is reachable.

    The default matches the container port-forward used by the ChatGPT desktop
    app (host: ``localhost:8000``).  Override with ``ARASAAC_PUBLIC_BASE_URL``.
    """
    return os.environ.get("ARASAAC_PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")


def default_output_dir() -> Path:
    """Where debug renders are written (``ARASAAC_OUTPUT_DIR`` or ``./output``)."""
    env = os.environ.get("ARASAAC_OUTPUT_DIR")
    return Path(env) if env else Path.cwd() / "output"


@dataclass
class ServerContext:
    """Everything a tool needs that is not per-call state.

    ``output_dir`` is ``None`` when saving is disabled (``--no-save``).
    """

    catalog: Catalog
    output_dir: Path | None
