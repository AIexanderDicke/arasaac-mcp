"""Pictogram catalog: word-based search and resolution over ARASAAC icons.

This is the word-based core behind the MCP server.  The caller searches and
refers to pictograms by German **word**, never by numeric id or file name.

Retrieval is built from words only: the description records
(``icons/descriptions.jsonl`` or ``icons/descriptions/<lang>/…``, see
:mod:`arasaac_mcp.descriptions`) plus the ``metadata_de.json`` shipped alongside
them (German keywords, tags, categories).  The pictogram PNG set is **never**
a source of retrieval information — files are located by id only for the final
display, and ``ensure`` fetches by ARASAAC id on demand
(:mod:`arasaac_mcp.fetch`).

Keep this module free of host specifics and of Pillow: it only maps words to
pictograms.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .descriptions import DescriptionRecord, load_descriptions
from .fetch import PictogramFetchError, fetch_pictogram

#: Roles accepted in layout trees (Fitzgerald key, see ``scripts/prompt.md``).
VALID_ROLES: tuple[str, ...] = ("PERSON", "NOUN", "VERB", "QUALITY", "SOCIAL", "MISC")


@dataclass(frozen=True)
class Pictogram:
    """One pictogram as the agent sees it: a file plus its German words."""

    file: str
    desc: str
    keywords: tuple[str, ...] = ()
    extra: tuple[str, ...] = ()
    pic_id: int | None = None


@dataclass(frozen=True)
class SearchHit:
    """A scored search result."""

    pic: Pictogram
    value: float


def default_icons_dir(cwd: Path | str | None = None) -> Path:
    """Locate the icons directory.

    Precedence: ``ARASAAC_ICONS_DIR``, then ``<cwd>/icons``, then
    ``<cwd>/../icons`` (so the tools work from ``src/`` subdirectories too).
    """
    base = Path(cwd) if cwd is not None else Path.cwd()
    candidates: list[Path] = []
    env = os.environ.get("ARASAAC_ICONS_DIR")
    if env:
        candidates.append(Path(env))
    candidates += [base / "icons", base.parent / "icons"]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return base / "icons"


def _natural_key(name: str) -> list[object]:
    """Locale-independent 'natural' key: ``2`` sorts before ``10``."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def _tokenize(query: str) -> list[str]:
    # Unicode-aware runs of letters/digits; underscores separate tokens.
    return [token.lower() for token in re.findall(r"[^\W_]+", query)]


def _score(
    pic: Pictogram, tokens: Iterable[str], description: DescriptionRecord | None = None
) -> float:
    """Higher is better.  Every token must match somewhere (AND).

    Sources, in descending value: an exact/partial German keyword, an exact
    synonym from the LLM description files, a (longer-token) fragment of the
    description text, and lastly the official tags/categories.  The pictogram
    PNG set is not a source: ``desc`` is metadata-derived words only.
    """
    text = description.text.lower() if description else ""
    synonyms = [synonym.lower() for synonym in (description.synonyms if description else ())]
    total = 0.0
    for token in tokens:
        best = 0
        for keyword in pic.keywords:
            value = keyword.lower()
            if value == token:
                best = max(best, 6)
            elif value.startswith(token) or (
                len(token) >= 4 and len(value) >= 3 and token.startswith(value)
            ):
                best = max(best, 4)
            elif token in value:
                best = max(best, 2)
        if token in synonyms:
            best = max(best, 4)
        elif len(token) >= 4 and token in text:
            best = max(best, 3)
        for value in pic.extra:
            if token in value.lower():
                best = max(best, 1)
        if best == 0:
            return 0.0  # require all tokens to match somewhere
        total += best
    return total - len(pic.keywords) * 0.01


_INDEX_CACHE: dict[str, list[Pictogram]] = {}


def _slug(text: str) -> str:
    """Filename slug, matching ``scripts/download_icons.py``."""
    text = re.sub(r"[^\w.-]+", "_", text, flags=re.UNICODE)
    return text.strip("_")[:60] or "pictogram"


def _first_keyword(entry: dict) -> str:
    for item in entry.get("keywords", []):
        keyword = str(item.get("keyword", "")).strip()
        if keyword:
            return keyword
    return ""


def _synthesize_file(pic_id: int, entry: dict) -> str:
    """The filename ``download_icons.py`` would have written for ``pic_id``."""
    keyword = _first_keyword(entry)
    return f"{pic_id}_{_slug(keyword)}.png" if keyword else f"{pic_id}.png"


def _load_index(icons_dir: Path) -> list[Pictogram]:
    """Build the word view purely from ``metadata_de.json`` — never from the
    pictogram PNG set (retrieval uses metadata + description data only)."""
    key = str(icons_dir)
    cached = _INDEX_CACHE.get(key)
    if cached is not None:
        return cached

    metadata_path = icons_dir / "metadata_de.json"
    pics: list[Pictogram] = []
    if metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        for entry in metadata:
            pic_id = entry.get("_id")
            if pic_id is None:
                continue
            file = _synthesize_file(pic_id, entry)
            keywords = tuple(
                str(item.get("keyword", "")).strip()
                for item in entry.get("keywords", [])
                if str(item.get("keyword", "")).strip()
            )
            extra = tuple(
                _dedupe(
                    [str(value) for value in [*entry.get("tags", []), *entry.get("categories", [])]]
                )
            )
            desc = _first_keyword(entry) or Path(file).stem
            pics.append(Pictogram(file, desc, keywords, extra, pic_id))

    _INDEX_CACHE[key] = pics
    return pics


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


class Catalog:
    """Word-based view over one icons directory."""

    def __init__(
        self,
        icons_dir: Path | str | None = None,
        *,
        cache_dir: Path | str | None = None,
        fetch_missing: bool = False,
        fetch_size: int = 500,
        static_url: str | None = None,
    ) -> None:
        self.icons_dir = Path(icons_dir) if icons_dir is not None else default_icons_dir()
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.fetch_missing = fetch_missing
        self.fetch_size = fetch_size
        self.static_url = static_url
        self._pics = _load_index(self.icons_dir)
        self._counts: dict[str, int] | None = None
        self._by_id: dict[int, Pictogram] | None = None
        self._desc_text: dict[int, DescriptionRecord] = load_descriptions(self.icons_dir)
        self._local_files: dict[Path, dict[int, list[str]]] = {}

    # -- indexing ----------------------------------------------------------

    @property
    def pictures(self) -> list[Pictogram]:
        return self._pics

    def by_id(self, pic_id: int) -> Pictogram | None:
        """The pictogram with this ARASAAC id, or ``None``."""
        if self._by_id is None:
            self._by_id = {pic.pic_id: pic for pic in self._pics if pic.pic_id is not None}
        return self._by_id.get(pic_id)

    def _keyword_counts(self) -> dict[str, int]:
        """How many pictograms share each keyword (used for qualifiers)."""
        if self._counts is None:
            counts: dict[str, int] = {}
            for pic in self._pics:
                for keyword in {keyword.lower() for keyword in pic.keywords}:
                    counts[keyword] = counts.get(keyword, 0) + 1
            self._counts = counts
        return self._counts

    # -- agent-facing words ------------------------------------------------

    def word_of(self, pic: Pictogram) -> str:
        """The word the agent sees and uses: the pictogram's main keyword."""
        return pic.keywords[0] if pic.keywords else pic.desc

    def label_of(self, pic: Pictogram) -> str:
        """Agent-facing label; adds a unique synonym when the word is shared.

        E.g. ``Schüler (Student)``.  Still no numbers or file names.
        """
        counts = self._keyword_counts()
        primary = self.word_of(pic)
        if counts.get(primary.lower(), 0) <= 1:
            return primary
        unique = next(
            (kw for kw in pic.keywords if counts.get(kw.lower(), 0) == 1),
            None,
        )
        if unique and unique.lower() != primary.lower():
            return f"{primary} ({unique})"
        return primary

    # -- search ------------------------------------------------------------

    def search(self, query: str, limit: int = 25) -> list[SearchHit]:
        """Search by German keyword(s); all tokens must match (AND)."""
        tokens = _tokenize(query)
        if not tokens:
            return []
        scored = [
            SearchHit(
                pic,
                _score(
                    pic, tokens, self._desc_text.get(pic.pic_id) if pic.pic_id is not None else None
                ),
            )
            for pic in self._pics
        ]
        scored = [hit for hit in scored if hit.value > 0]
        return self._dedupe_by_label(scored)[: max(1, min(limit, 100))]

    def _dedupe_by_label(self, hits: list[SearchHit]) -> list[SearchHit]:
        seen: dict[str, SearchHit] = {}
        for hit in hits:
            key = self.label_of(hit.pic).lower()
            current = seen.get(key)
            if current is None or hit.value > current.value:
                seen[key] = hit
        ranked = sorted(seen.values(), key=lambda hit: hit.value, reverse=True)
        return ranked

    def search_lines(self, query: str, limit: int = 25) -> list[str]:
        """Formatted, word-only result lines as shown to the agent."""
        lines: list[str] = []
        for index, hit in enumerate(self.search(query, limit)):
            synonyms = ", ".join(hit.pic.keywords[1:])
            extras = ", ".join(hit.pic.extra[:4])
            detail = "; ".join(
                part
                for part in (
                    f"Synonyme: {synonyms}" if synonyms else "",
                    f"Tags: {extras}" if extras else "",
                )
                if part
            )
            label = self.label_of(hit.pic)
            lines.append(f"{index + 1}. {label}{f' — {detail}' if detail else ''}")
        return lines

    # -- resolution --------------------------------------------------------

    def resolve(self, word: str) -> Pictogram:
        """Resolve an agent word (or ``Base (Qualifier)`` label) to a pictogram."""
        match = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", word.strip())
        base = (match.group(1) if match else word).strip()
        qualifier = (match.group(2) if match else "").strip().lower()
        base_lower = base.lower()

        candidates = [
            pic
            for pic in self._pics
            if any(keyword.lower() == base_lower for keyword in pic.keywords)
        ]
        if not candidates:
            candidates = [pic for pic in self._pics if self.word_of(pic).lower() == base_lower]
        if qualifier:
            qualified = [
                pic
                for pic in candidates
                if any(keyword.lower() == qualifier for keyword in pic.keywords)
            ]
            if qualified:
                candidates = qualified
        if candidates:
            exact = [pic for pic in candidates if self.word_of(pic).lower() == base_lower]
            # Prefer the candidate whose (unqualified) label matches the query,
            # so `Auto` resolves to the pictogram labelled `Auto`, not `Auto (KFZ)`.
            plain = [pic for pic in exact if self.label_of(pic).lower() == base_lower]
            pool = plain or exact or candidates
            return min(pool, key=lambda pic: _natural_key(pic.file))

        # Fall back to fuzzy search over all keywords/tags.
        tokens = _tokenize(" ".join(part for part in (base, qualifier) if part))
        best: Pictogram | None = None
        best_value = 0.0
        for pic in self._pics:
            value = _score(pic, tokens)
            if value > best_value:
                best_value = value
                best = pic
        if best is None:
            raise KeyError(
                f"No pictogram found for {word!r}. Search for a simpler word or a synonym."
            )
        return best

    def resolve_file(self, word: str) -> Path:
        """Resolve a word to a local file path, fetching it if needed."""
        return self.ensure(self.resolve(word))

    def _id_files(self, base: Path) -> dict[int, list[str]]:
        """Local PNG names per ARASAAC id, found by id prefix only.

        This is display bookkeeping — a local ``<id>_*.png`` may always be
        rendered — and never influences search or resolution.
        """
        cached = self._local_files.get(base)
        if cached is not None:
            return cached
        by_id: dict[int, list[str]] = {}
        try:
            for name in os.listdir(base):
                if not name.endswith(".png"):
                    continue
                match = re.match(r"^(\d+)_", name)
                if match:
                    by_id.setdefault(int(match.group(1)), []).append(name)
        except FileNotFoundError:
            pass
        self._local_files[base] = by_id
        return by_id

    def _locate(self, pic: Pictogram) -> Path | None:
        """Local path to ``pic`` if one exists (cache dir first).

        The files are addressed by ARASAAC id — the descriptive part of a
        local filename is irrelevant for display.
        """
        for base in (self.cache_dir, self.icons_dir):
            if base is None:
                continue
            if pic.pic_id is not None:
                for name in self._id_files(base).get(pic.pic_id, []):
                    path = base / name
                    if path.is_file():
                        return path
            path = base / pic.file
            if path.is_file():
                return path
        return None

    def ensure(self, pic: Pictogram) -> Path:
        """Return a local path to ``pic``, downloading it when allowed.

        Addressing is purely id-based: an existing local ``<id>_*.png`` (cache
        directory first) is used for whatever name it carries; when it is
        missing and ``fetch_missing`` is on, the PNG is fetched from ARASAAC
        **by id** into ``cache_dir`` (or the icons directory) and cached for
        the next call.  Otherwise a :class:`FileNotFoundError` is raised —
        callers never render a placeholder, because a wrong icon is worse
        than none.  The pictogram set itself is never a retrieval source.
        """
        located = self._locate(pic)
        if located is not None:
            return located

        if not self.fetch_missing:
            raise FileNotFoundError(
                f"pictogram not available locally: {pic.file} ({self.word_of(pic)}); "
                "start the server with icon fetching enabled (ARASAAC_FETCH=on)"
            )
        if pic.pic_id is None:
            raise FileNotFoundError(
                f"pictogram not available locally and has no ARASAAC id: {pic.file}"
            )
        target = (self.cache_dir or self.icons_dir) / pic.file
        try:
            fetch_pictogram(
                pic.pic_id,
                target,
                size=self.fetch_size,
                static_url=self.static_url,
            )
        except PictogramFetchError as exc:
            raise FileNotFoundError(
                f"could not fetch pictogram {pic.file} ({self.word_of(pic)}): {exc}"
            ) from exc
        return target

    def path_of(self, word: str) -> Path:
        """Resolve a word and return a local file, fetching it if needed."""
        return self.ensure(self.resolve(word))

    # -- layout tree -------------------------------------------------------

    def icon_node(self, word: str, **extra: object) -> dict:
        """Turn a word into a resolved icon node (word -> file + concept)."""
        pic = self.resolve(word)
        return {
            "type": "icon",
            "file": str(self.ensure(pic)),
            "concept": self.label_of(pic),
            **extra,
        }

    def _resolve_cell(self, cell: object) -> dict | None:
        """Resolve a grid cell, keeping its position (an empty cell = ``None``)."""
        if isinstance(cell, str) and not cell.strip():
            return None
        return self.resolve_layout_node(cell)

    def resolve_layout_node(self, node: object) -> dict | None:
        """Recursively replace ``word`` with ``file``/``concept`` in a layout tree.

        See ``scripts/prompt.md`` §9 for the node types.  Strings are icon words,
        lists become columns, and grid cells stay positional (empty = ``None``).
        """
        if node is None:
            return None
        if isinstance(node, str):
            return self.icon_node(node)
        if isinstance(node, list):
            return {
                "type": "column",
                "gap": 6,
                "children": [
                    resolved
                    for resolved in (self.resolve_layout_node(child) for child in node)
                    if resolved is not None
                ],
            }
        if not isinstance(node, dict):
            raise TypeError(f"Invalid layout node: {node!r}")

        out = dict(node)
        if isinstance(out.get("word"), str):
            pic = self.resolve(out["word"])
            if out.get("file") is None:
                out["file"] = str(self.ensure(pic))
            if out.get("concept") is None and out.get("text") is None:
                out["concept"] = self.label_of(pic)
            del out["word"]
        if out.get("role") is not None:
            role = str(out["role"]).upper()
            if role not in VALID_ROLES:
                raise ValueError(
                    f'Invalid role "{out["role"]}" (expected: {", ".join(VALID_ROLES)})'
                )
            out["role"] = role
        for key in ("children", "items"):
            if out.get(key) is not None:
                value = out[key]
                items = value if isinstance(value, list) else [value]
                out[key] = [
                    resolved
                    for resolved in (self.resolve_layout_node(child) for child in items)
                    if resolved is not None
                ]
        for key in ("child", "node"):
            if out.get(key) is not None:
                out[key] = self.resolve_layout_node(out[key])
        if isinstance(out.get("cells"), list):
            # Keep positions: an empty cell is `None`, not a removed entry.
            out["cells"] = [self._resolve_cell(cell) for cell in out["cells"]]
        if isinstance(out.get("rows"), list):
            rows: list[object] = []
            for row in out["rows"]:
                if isinstance(row, list):
                    rows.append({"cells": [self._resolve_cell(cell) for cell in row]})
                elif isinstance(row, dict):
                    copy = dict(row)
                    if isinstance(copy.get("cells"), list):
                        copy["cells"] = [self._resolve_cell(cell) for cell in copy["cells"]]
                    rows.append(copy)
                else:
                    rows.append(row)
            out["rows"] = rows
        return out


_CATALOG_CACHE: dict[tuple, Catalog] = {}


def get_catalog(
    icons_dir: Path | str | None = None,
    *,
    cache_dir: Path | str | None = None,
    fetch_missing: bool = False,
    fetch_size: int = 500,
    static_url: str | None = None,
) -> Catalog:
    """Return a cached :class:`Catalog` for an icons directory and fetch policy."""
    resolved = Path(icons_dir) if icons_dir is not None else default_icons_dir()
    key = (
        str(resolved),
        str(cache_dir) if cache_dir is not None else None,
        fetch_missing,
        fetch_size,
        static_url,
    )
    catalog = _CATALOG_CACHE.get(key)
    if catalog is None:
        catalog = Catalog(
            resolved,
            cache_dir=cache_dir,
            fetch_missing=fetch_missing,
            fetch_size=fetch_size,
            static_url=static_url,
        )
        _CATALOG_CACHE[key] = catalog
    return catalog
