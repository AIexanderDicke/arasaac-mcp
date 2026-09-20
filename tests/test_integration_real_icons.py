"""Integration checks against the real ARASAAC metadata/PNG set.

These are skipped automatically when ``icons/metadata_de.json`` (or the PNGs)
are not available, so a clean checkout still runs the offline suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastmcp import Client

from arasaac_mcp.catalog import Catalog, get_catalog
from arasaac_mcp.mcp import create_server

pytestmark = pytest.mark.integration


def test_real_catalog_indexes_thousands_of_pictograms(real_icons_dir: Path) -> None:
    catalog = Catalog(real_icons_dir)
    assert len(catalog.pictures) > 1000


def test_real_catalog_search_returns_the_exact_word(real_icons_dir: Path) -> None:
    catalog = get_catalog(real_icons_dir)
    lines = catalog.search_lines("Regen", 5)
    assert lines
    assert lines[0].startswith("1. Regen")


@pytest.mark.parametrize("query", ["Schüler", "Auto", "vor", "Sport", "Regen", "Familie"])
def test_real_catalog_labels_round_trip(real_icons_dir: Path, query: str) -> None:
    catalog = get_catalog(real_icons_dir)
    for line in catalog.search_lines(query, 12):
        label = line.split(". ", 1)[1].split(" — ")[0].strip()
        assert catalog.label_of(catalog.resolve(label)) == label


def test_real_catalog_resolves_a_word_to_an_existing_file(real_icons_dir: Path) -> None:
    catalog = Catalog(real_icons_dir)
    pic = catalog.resolve("Regen")
    path = catalog.ensure(pic)
    assert path.is_file()


async def test_real_mcp_render_produces_a_sheet(real_icons_dir: Path, tmp_path: Path) -> None:
    catalog = Catalog(real_icons_dir)
    try:
        catalog.ensure(catalog.resolve("Regen"))
        catalog.ensure(catalog.resolve("Auto"))
    except FileNotFoundError:
        pytest.skip("local PNGs are not available (metadata-only checkout)")

    server = create_server(real_icons_dir, output_dir=tmp_path, fetch_missing=False)
    async with Client(server) as client:
        result = await client.call_tool(
            "render_pictogram_sheet", {"words": ["Regen", "Auto"], "sentence": "Test"}
        )
    assert "Image: " in result.content[0].text
    assert list(tmp_path.glob("sheet_*.png"))
