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


def fetch_missing_enabled() -> bool:
    """Whether missing pictograms may be fetched live (``ARASAAC_FETCH``).

    Defaults to on ("auto"): a pictogram already on disk is always used, the
    network is only touched for one that is missing.  Set ``ARASAAC_FETCH=off``
    for an offline / air-gapped run.
    """
    value = os.environ.get("ARASAAC_FETCH", "auto").strip().lower()
    return value not in {"off", "0", "false", "no", "never"}


def default_cache_dir() -> Path | None:
    """Writable pictogram cache (``ARASAAC_CACHE_DIR``), or ``None``."""
    env = os.environ.get("ARASAAC_CACHE_DIR")
    return Path(env) if env else None


def default_fetch_size() -> int:
    """Icon width to request (``ARASAAC_FETCH_SIZE``, default 500)."""
    try:
        return int(os.environ.get("ARASAAC_FETCH_SIZE", "500"))
    except ValueError:
        return 500


@dataclass
class ServerContext:
    """Everything a tool needs that is not per-call state.

    ``output_dir`` is ``None`` when saving is disabled (``--no-save``).
    """

    catalog: Catalog
    output_dir: Path | None
