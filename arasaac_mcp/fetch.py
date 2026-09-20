"""Fetch ARASAAC pictograms on demand (stdlib only, no Pillow).

The catalog is built from ``metadata_de.json`` alone, so the Docker image no
longer has to bundle the ~338 MB pictogram set.  A pictogram is downloaded
**only** when a word needs to be rendered and the PNG is not already on disk;
the download is written into a cache directory (write-through), so the next
render is local again.

Downloads are atomic (temp file + ``os.replace``), so an interrupted fetch
never leaves a truncated PNG behind.  ARASAAC serves the same pictogram at
several widths; the requested size is tried first and the rest fall back,
mirroring ``scripts/download_icons.py``.
"""

from __future__ import annotations

import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

#: ARASAAC static server prefix; ``<base>/<id>/<id>_<size>.png``.
DEFAULT_STATIC_URL = "https://static.arasaac.org/pictograms"

#: Fallback widths tried when the requested one is not served.
FALLBACK_SIZES: tuple[int, ...] = (300, 2500)


class PictogramFetchError(RuntimeError):
    """A pictogram could not be downloaded (offline, 4xx/5xx, empty body)."""


def default_static_url() -> str:
    """Static server prefix, overridable with ``ARASAAC_STATIC_URL``."""
    return os.environ.get("ARASAAC_STATIC_URL", DEFAULT_STATIC_URL).rstrip("/")


def _download(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "arasaac-mcp"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_pictogram(
    pic_id: int,
    dest: Path,
    size: int = 500,
    *,
    static_url: str | None = None,
    timeout: float = 30.0,
) -> Path:
    """Download pictogram ``pic_id`` to ``dest`` and return ``dest``.

    Tries ``size`` first, then :data:`FALLBACK_SIZES`.  Raises
    :class:`PictogramFetchError` if every candidate fails, so callers can report
    a clear error instead of rendering a placeholder.
    """
    base = (static_url or default_static_url()).rstrip("/")
    sizes = (size, *(candidate for candidate in FALLBACK_SIZES if candidate != size))
    failures: list[str] = []
    for candidate in sizes:
        url = f"{base}/{pic_id}/{pic_id}_{candidate}.png"
        try:
            data = _download(url, timeout)
        except (urllib.error.URLError, OSError) as exc:  # URLError is an OSError too
            failures.append(f"{candidate}px: {exc}")
            continue
        if not data:
            failures.append(f"{candidate}px: empty response")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        handle, tmp_name = tempfile.mkstemp(
            dir=dest.parent, prefix=f".{dest.name}.", suffix=".tmp"
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
            os.replace(tmp_path, dest)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
        return dest
    raise PictogramFetchError(
        f"could not download pictogram {pic_id}: " + "; ".join(failures)
    )
