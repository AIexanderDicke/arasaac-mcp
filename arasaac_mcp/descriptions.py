"""Loader for the LLM icon description records.

The description files are the primary retrieval corpus for both search tools
(:mod:`arasaac_mcp.catalog` lexical search and the Qdrant vector layer in
:mod:`arasaac_mcp.vector`).  Loading is purely textual — no PNG is opened and
the on-disk pictogram set is irrelevant here.

Two layouts are supported (checked in this order):

- ``<icons-dir>/descriptions.jsonl`` — one JSON record per line
  (the consolidated, git-tracked English set);
- ``<icons-dir>/descriptions/**`` — per-icon ``[id]_description.json`` files,
  flat or per language (``descriptions/en/…``), as written by
  ``scripts/generate_icon_descriptions.py``.

Everything is absent-safe: a missing source yields an empty mapping, never an
error, so callers fall back to metadata-only behaviour.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

#: Pictograms whose description is regenerable default to ``en``.
DEFAULT_LANGUAGE = "en"

_JSON_NAME = "_description.json"


@dataclass(frozen=True)
class DescriptionRecord:
    """One structured description of one pictogram."""

    id: int
    description: str
    usage: str
    synonyms: tuple[str, ...]

    @property
    def text(self) -> str:
        """Everything retrievable, joined for token matching."""
        return " ".join(part for part in (self.description, self.usage, *self.synonyms) if part)


#: Loaded description sources per icons dir (module-level, like the catalog).
_CACHE: dict[str, dict[int, DescriptionRecord]] = {}


def find_source(icons_dir: Path, lang: str = DEFAULT_LANGUAGE) -> Path | None:
    """The description source for ``lang``: JSONL first, then the per-icon
    directory layout (``<dir>/<lang>/*.json``, else flat ``*.json``)."""
    jsonl = Path(icons_dir) / "descriptions.jsonl"
    if jsonl.is_file():
        return jsonl
    base = Path(icons_dir) / "descriptions"
    language_dir = base / lang
    if language_dir.is_dir():
        return language_dir
    if base.is_dir():
        return base
    return None


def load_descriptions(
    icons_dir: Path | str | None = None, lang: str = DEFAULT_LANGUAGE
) -> dict[int, DescriptionRecord]:
    """Read the description records for ``lang``, keyed by pictogram id.

    Cached per (icons dir, language); missing or empty sources map to ``{}``.
    Records without an integer ``id`` or empty ``description`` are skipped.
    """
    from .catalog import default_icons_dir  # reuses the env resolution

    directory = Path(icons_dir) if icons_dir is not None else default_icons_dir()
    key = f"{directory}::{lang}"
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    source = find_source(directory, lang)
    records: dict[int, DescriptionRecord] = {}
    if source is not None:
        records = _load_jsonl(source) if source.suffix == ".jsonl" else _load_directory(source)
    _CACHE[key] = records
    return records


def _record_from_json(data: object) -> DescriptionRecord | None:
    if not isinstance(data, dict):
        return None
    pic_id = data.get("id")
    description = str(data.get("description") or "").strip()
    if not isinstance(pic_id, int) or not description:
        return None
    usage = str(data.get("usage") or "").strip()
    synonyms = tuple(str(value) for value in data.get("synonyms") or [] if str(value).strip())
    return DescriptionRecord(pic_id, description, usage, synonyms)


def _load_jsonl(path: Path) -> dict[int, DescriptionRecord]:
    records: dict[int, DescriptionRecord] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = _record_from_json(json.loads(line))
        except ValueError:
            continue
        if record is not None:
            records[record.id] = record
    return records


def _load_directory(source: Path) -> dict[int, DescriptionRecord]:
    records: dict[int, DescriptionRecord] = {}
    for path in sorted(source.rglob(f"*{_JSON_NAME}")):
        try:
            record = _record_from_json(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, UnicodeDecodeError):
            continue
        if record is not None:
            records[record.id] = record
    return records


def description_for(
    pic_id: int | None, icons_dir: Path | str | None = None, lang: str = DEFAULT_LANGUAGE
) -> DescriptionRecord | None:
    """The description record of one pictogram, or ``None``."""
    if pic_id is None:
        return None
    return load_descriptions(icons_dir, lang).get(pic_id)


def _reset_cache() -> None:
    """Drop the cached mappings (test isolation)."""
    for key in list(_CACHE):
        del _CACHE[key]
