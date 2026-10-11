#!/usr/bin/env python
"""Manual end-to-end test for the semantic pictogram search.

Checks the Docker Qdrant (collection stats), then runs a demo query set in
German and English through every search mode of the
``semantic_search_pictograms`` tool and, for comparison, through the lexical
``search_pictograms``.  Every shown label must resolve back to the same
pictogram (the word contract), which the script asserts per query.

The embedding provider is whatever ``ARASAAC_EMBED_*`` / the flags below
configure — the script does not touch the database with an offline fallback.

Exit codes: 0 all checks passed, 1 one or more failures, 2 environment
missing (Qdrant unreachable / collection empty).

    docker compose up -d qdrant
    uv run python scripts/semantic_search_manual.py
    uv run python scripts/semantic_search_manual.py --mode hybrid --limit 3
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arasaac_mcp.catalog import Catalog, default_icons_dir
from arasaac_mcp.embeddings import EmbeddingError, make_embedder
from arasaac_mcp.mcp.search_pictograms import search as lexical_search
from arasaac_mcp.mcp.semantic_search_pictograms import search as semantic_search
from arasaac_mcp.vector import VectorDBError, VectorIndex, qdrant_url

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_ENV = 2

#: Demo queries: German requests the agent would realistically get.
DEMO_QUERIES: tuple[str, ...] = (
    "die Katze trinkt Milch",
    "Ein Hund läuft über die Wiese",
    "rote Ampel an einer Straße",
    "Kind lernt schreiben in der Schule",
    "Es regnet stark draußen",
    "Fahrrad reparatur Werkzeug",
    "Arzt untersucht Patient",
    "eat an apple",
    "firefighter extinguishes a fire",
)


def label_from_line(line: str) -> str:
    """The agent-facing label of a result line (``"1. Label (Syn) — …"``)."""
    body = line.split(". ", 1)[1]
    return body.split(" — ", 1)[0]


def check_collection(url: str, collection: str, check_empty: bool) -> VectorIndex | None:
    """Return the index when the database and collection are usable."""
    try:
        index = VectorIndex.open(url, collection)
        points = index.count()
    except Exception as exc:
        print(f"FAIL  Qdrant unreachable at {url}: {exc}")
        print("      start the database with: docker compose up -d qdrant")
        return None
    dim = index.dimension()
    print(f"CHECK collection '{collection}' at {url}: {points} points, dim={dim}")
    if check_empty and points == 0:
        print(
            "FAIL  collection is empty — run the ingest script first:\n"
            "      uv run python scripts/index_descriptions.py"
        )
        return None
    return index


def run_queries(
    catalog: Catalog,
    index: VectorIndex,
    embedder,
    limit: int,
    modes: list[str],
    boost: bool,
) -> int:
    """Run the demo queries through every mode; returns the failure count."""
    failures = 0
    for query in DEMO_QUERIES:
        lexical = lexical_search(catalog, query, limit=limit)
        for mode in modes:
            message = semantic_search(
                catalog,
                index,
                embedder,
                query,
                limit=limit,
                mode=mode,
                boost=boost,
            )
            if message.startswith(("Semantic search failed", "Unknown search mode")):
                print(f"FAIL  [{mode}] {query!r}: {message.splitlines()[0]}")
                failures += 1
                continue
            lines = message.splitlines()[1:]
            labels = [label_from_line(line) for line in lines]
            broken = [label for label in labels if not _resolves(catalog, label)]
            status = "FAIL" if broken else "OK  "
            failures += len(broken)
            print(f"{status} [{mode:9}] {query!r}")
            print(f"      semantic: {' | '.join(labels) if labels else '(none)'}")
            if broken:
                print(f"      labels that do not resolve: {broken}")
        lex_labels = [label_from_line(line) for line in lexical.splitlines()[1:]]
        print(f"      lexical : {' | '.join(lex_labels) if lex_labels else '(none)'}")
    return failures


def _resolves(catalog: Catalog, label: str) -> bool:
    try:
        catalog.resolve(label)
        return True
    except KeyError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="semantic-search-manual",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--qdrant-url", default=qdrant_url())
    parser.add_argument("--collection", default=None)
    parser.add_argument("--icons-dir", default=None)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--mode", action="append", default=None)
    parser.add_argument("--boost", action="store_true")
    parser.add_argument("--no-check-empty", action="store_true")
    args = parser.parse_args(argv)

    modes = args.mode or ["semantic", "synonyms", "hybrid"]
    icons_dir = args.icons_dir or default_icons_dir()
    catalog = Catalog(icons_dir)
    collection = args.collection
    if collection is None:
        from arasaac_mcp.vector import collection_name

        collection = collection_name()

    index = check_collection(args.qdrant_url, collection, check_empty=not args.no_check_empty)
    if index is None:
        return EXIT_ENV
    try:
        embedder = make_embedder()
        probe = embedder.embed(["probe"])[0]
    except (EmbeddingError, VectorDBError) as exc:
        print(f"FAIL  embedding model not usable: {exc}")
        return EXIT_ENV
    print(f"CHECK embedder '{embedder.model_name}' → {len(probe)} dims")

    failures = run_queries(catalog, index, embedder, args.limit, modes, args.boost)
    if failures:
        print(f"\nRESULT {failures} failing check(s)")
        return EXIT_FAILED
    print("\nRESULT all checks passed")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
