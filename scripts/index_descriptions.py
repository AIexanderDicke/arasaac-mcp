#!/usr/bin/env python
"""Ingest the LLM icon descriptions into the Qdrant vector database.

Joins the per-icon description records (``icons/descriptions.jsonl``, English;
or ``<descriptions-dir>/<lang>/*.json``) with the catalog metadata
(keywords/tags/categories) and writes one Qdrant point per pictogram:

- vector ``text``: embedding of description + usage
- vector ``syn``: embedding of synonyms + German keywords
- payload: label, keywords, synonyms, tags, categories (indexed for filters)

The run is chunked, retried and resumable: points already in the collection are
skipped unless ``--force``.  The database must be running as a Docker container
(``docker compose up -d qdrant``); the script has no fallback database.

Example::

    uv run python scripts/index_descriptions.py \
        --embed-model liquid/lfm-2.5-embedding-350m:free \
        --embed-batch-size 128
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arasaac_mcp.catalog import Catalog
from arasaac_mcp.embeddings import (
    Embedder,
    EmbeddingError,
    embed_batch_size,
    embed_provider,
    make_embedder,
    probe_dim,
)
from arasaac_mcp.vector import (
    DEFAULT_COLLECTION,
    DEFAULT_QDRANT_URL,
    PicRecord,
    VectorDBError,
    VectorIndex,
    collection_name,
    qdrant_url,
)

#: Exit codes, mirroring scripts/generate_icon_descriptions.py.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def load_jsonl_records(path: Path) -> list[dict]:
    """Description records from a ``.jsonl`` file (one JSON object per line).

    Bad lines are skipped, so a partially written file still ingests.
    """
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        pic_id = record.get("id")
        if isinstance(pic_id, int) and record.get("description"):
            records.append(record)
    return records


def load_dir_records(descriptions_dir: Path, pattern: str) -> list[dict]:
    """Description records from per-icon JSON files (flat or per language)."""
    records: list[dict] = []
    for path in sorted(descriptions_dir.rglob(pattern)):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        pic_id = record.get("id")
        if isinstance(pic_id, int) and record.get("description"):
            records.append(record)
    return records


def load_records(
    descriptions_file: Path | None,
    descriptions_dir: Path | None,
    lang: str,
) -> list[dict]:
    """Records from the JSONL source, else from the description directory."""
    if descriptions_file is not None:
        return load_jsonl_records(descriptions_file)
    if descriptions_dir is not None:
        return load_dir_records(descriptions_dir, "*.json")
    raise ValueError("neither descriptions-file nor descriptions-dir given")


def load_metadata(icons_dir: Path) -> dict[int, dict]:
    """Raw ``metadata_de.json`` objects keyed by id (tags/categories)."""
    path = icons_dir / "metadata_de.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {entry["_id"]: entry for entry in data if isinstance(entry.get("_id"), int)}


def build_records(
    catalog: Catalog,
    metadata: dict[int, dict],
    descriptions: list[dict],
) -> tuple[list[PicRecord], int]:
    """Join descriptions with metadata into :class:`PicRecord` s.

    Returns the records and the number of description entries that had no
    matching icon (or no description text) and were skipped.
    """
    records: list[PicRecord] = []
    skipped = 0
    for entry in descriptions:
        pic = catalog.by_id(int(entry["id"]))
        if pic is None:
            skipped += 1
            continue
        raw = metadata.get(int(entry["id"]), {})
        synonyms = tuple(str(value) for value in entry.get("synonyms") or [] if str(value).strip())
        record = PicRecord(
            pic_id=int(entry["id"]),
            label=catalog.label_of(pic),
            word=catalog.word_of(pic),
            file_stem=Path(pic.file).stem,
            description=str(entry["description"]).strip(),
            usage=str(entry.get("usage") or "").strip(),
            synonyms=synonyms,
            keywords=tuple(pic.keywords),
            tags=tuple(str(value) for value in raw.get("tags") or []),
            categories=tuple(str(value) for value in raw.get("categories") or []),
        )
        records.append(record)
    return records, skipped


def plan(args: argparse.Namespace) -> tuple[list[PicRecord], int]:
    """Collect and join the records to ingest (or to plan, when ``--dry-run``)."""
    icons_dir = Path(args.icons_dir)
    catalog = Catalog(icons_dir)
    metadata = load_metadata(icons_dir)
    descriptions = load_records(
        Path(args.descriptions_file) if args.descriptions_file else None,
        Path(args.descriptions_dir) if args.descriptions_dir else None,
        args.lang,
    )
    if args.limit:
        descriptions = descriptions[: args.limit]
    records, skipped = build_records(catalog, metadata, descriptions)
    return records, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="index-descriptions",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--qdrant-url", default=qdrant_url() or DEFAULT_QDRANT_URL)
    parser.add_argument("--collection", default=collection_name() or DEFAULT_COLLECTION)
    parser.add_argument("--icons-dir", default=None)
    parser.add_argument(
        "--descriptions-file",
        default=None,
        help="JSONL with description records (default: <icons-dir>/descriptions.jsonl)",
    )
    parser.add_argument(
        "--descriptions-dir",
        default=None,
        help="Directory with per-icon JSON records (default: <icons-dir>/descriptions)",
    )
    parser.add_argument("--lang", default="en")
    parser.add_argument("--embed-provider", default=embed_provider())
    parser.add_argument("--embed-model", default=None)
    parser.add_argument("--embed-base-url", default=None)
    parser.add_argument("--embed-api-key", default=None)
    parser.add_argument("--embed-batch-size", type=int, default=None)
    parser.add_argument("--embed-device", default=None)
    parser.add_argument("--embed-retries", type=int, default=None)
    parser.add_argument("--embed-backoff", type=float, default=None)
    parser.add_argument(
        "--embed-min-interval",
        type=float,
        default=None,
        help="Seconds between requests; use ~3.5 for rate-limited free models",
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--recreate", action="store_true", help="Drop and rebuild the collection")
    parser.add_argument("--force", action="store_true", help="Re-upsert points already stored")
    parser.add_argument("--dry-run", action="store_true", help="Only print the plan")
    args = parser.parse_args(argv)

    from arasaac_mcp.catalog import default_icons_dir

    icons_dir = args.icons_dir or default_icons_dir()
    args.icons_dir = str(icons_dir)
    if args.descriptions_file is None and args.descriptions_dir is None:
        file_default = Path(icons_dir) / "descriptions.jsonl"
        if file_default.is_file():
            args.descriptions_file = str(file_default)
        else:
            args.descriptions_dir = str(Path(icons_dir) / "descriptions")
    if (args.descriptions_file and not Path(args.descriptions_file).is_file()) or (
        args.descriptions_dir and not Path(args.descriptions_dir).is_dir()
    ):
        parser.error(
            f"description source not found: {args.descriptions_file or args.descriptions_dir}"
        )

    records, skipped = plan(args)
    print(f"pictograms to index: {len(records)}")
    if skipped:
        print(f"without description: {skipped}")
    if not records:
        print("nothing to ingest")
        return EXIT_OK
    if args.dry_run:
        print("dry run: nothing written")
        return EXIT_OK

    embedder = make_embedder(
        args.embed_provider,
        model=args.embed_model,
        base_url=args.embed_base_url,
        api_key=args.embed_api_key,
        device=args.embed_device,
        batch_size=args.embed_batch_size or embed_batch_size(),
        timeout=args.timeout,
        retries=args.embed_retries,
        backoff=args.embed_backoff,
        min_interval=args.embed_min_interval,
    )
    index = VectorIndex.open(args.qdrant_url, args.collection)

    try:
        print(f"probing embedding dimension ({embedder.model_name})…")
        dim = probe_dim(embedder)
        print(f"  dimension {dim}")
        created = index.ensure_collection(dim, recreate=args.recreate)
        if created:
            print(f"created collection {args.collection!r}")
        if not args.force and not created:
            print("scanning stored points for resumable skip…")
            stored_ids = index.existing_ids()
            todo = [r for r in records if r.pic_id not in stored_ids]
        else:
            todo = records
        print(f"points to ingest   : {len(todo)} (stored: {index.count()})")
        written = ingest(index, embedder, todo)
        print(f"ingested points    : {written}; collection now holds {index.count()}")
    except (VectorDBError, EmbeddingError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FAILED
    print("done")
    return EXIT_OK


def ingest(index: VectorIndex, embedder: Embedder, records: list[PicRecord]) -> int:
    """Embed and upsert ``records`` with progress output, in order."""
    written = 0
    batch = max(1, embed_batch_size())
    for start in range(0, len(records), batch):
        chunk = records[start : start + batch]
        text_vectors = embedder.embed([r.text_document() for r in chunk])
        syn_vectors = embedder.embed([r.syn_document() for r in chunk])
        vectors = [
            {"text": text, "syn": syn} for text, syn in zip(text_vectors, syn_vectors, strict=True)
        ]
        written += index.upsert(chunk, vectors)
        done = min(start + batch, len(records))
        print(f"  {done}/{len(records)} points")
    return written


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
