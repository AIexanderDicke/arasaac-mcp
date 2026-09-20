"""Shared builders for the test suite.

Everything here is test-only.  The fixtures build a tiny, fully synthetic
pictogram library (a handful of real PNG bytes plus a matching
``metadata_de.json``) so the tests never depend on the ~338 MB ARASAAC set,
on the network, or on a particular system font.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from PIL import Image

#: Metadata for the synthetic library.  Ordered like the real file (a list of
#: dump objects) and deliberately contains:
#:
#: * a unique word (``Regen``),
#: * a word shared by two pictograms with unique synonyms
#:   (``Auto`` -> ``Auto (KFZ)`` / ``Auto (Wagen)``),
#: * a word shared by two pictograms *without* a unique synonym
#:   (``Schüler``), which must fall back to the shared primary label,
#: * a short word used to exercise the forgiving stem match (``rot``).
SYNTHETIC_METADATA: list[dict] = [
    {"_id": 1, "keywords": [{"keyword": "Regen"}], "tags": ["Wetter"], "categories": ["Natur"]},
    {"_id": 2, "keywords": [{"keyword": "Auto"}, {"keyword": "KFZ"}], "tags": ["Fahrzeug"]},
    {"_id": 3, "keywords": [{"keyword": "Auto"}, {"keyword": "Wagen"}], "tags": ["Fahrzeug"]},
    {"_id": 4, "keywords": [{"keyword": "Schüler"}, {"keyword": "Student"}]},
    {"_id": 5, "keywords": [{"keyword": "Schüler"}, {"keyword": "Student"}]},
    {"_id": 6, "keywords": [{"keyword": "rot"}]},
    {"_id": 7, "keywords": [{"keyword": "Berg"}]},
]

#: ``[id]_[description].png`` files written for the metadata above, plus two
#: files that are *not* in the metadata (an id-prefixed and a bare one).
SYNTHETIC_FILES: tuple[str, ...] = (
    "1_Regen.png",
    "2_Auto.png",
    "3_Auto.png",
    "4_Schüler.png",
    "5_Schüler.png",
    "6_rot.png",
    "7_Berg.png",
    "999_unlisted.png",
    "orphan.png",
)


def make_png(path: Path, color: str = "#3366CC", size: int = 48) -> Path:
    """Write a small, deterministic solid-colour RGBA PNG."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (size, size), color).save(path, format="PNG")
    return path


def build_icons_dir(root: Path) -> Path:
    """Create a synthetic icons directory (PNGs + ``metadata_de.json``).

    Returns the directory path.  ``root`` is created if missing.
    """
    icons = root / "icons"
    icons.mkdir(parents=True, exist_ok=True)
    for index, name in enumerate(SYNTHETIC_FILES):
        hue = (index * 37) % 256
        make_png(icons / name, color=f"#{hue:02X}{(255 - hue):02X}80")
    (icons / "metadata_de.json").write_text(
        json.dumps(SYNTHETIC_METADATA, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return icons


def build_static_tree(static: Path, pic_ids: Iterable[int], size: int = 500) -> Path:
    """Create an ARASAAC-like ``<id>/<id>_<size>.png`` tree for live fetches.

    Used with ``ARASAAC_STATIC_URL=<static.as_uri()>`` so the on-demand fetch
    goes through ``urllib``'s ``file://`` handler instead of the network.
    """
    for pic_id in pic_ids:
        make_png(static / str(pic_id) / f"{pic_id}_{size}.png")
    return static
