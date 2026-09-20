"""The MCP tool functions, exercised directly (no transport)."""

from __future__ import annotations

from pathlib import Path

import pytest

from arasaac_mcp.catalog import Catalog
from arasaac_mcp.mcp.render_pictogram_layout import render_tree
from arasaac_mcp.mcp.render_pictogram_sheet import render_word_sheet
from arasaac_mcp.mcp.search_pictograms import search
from arasaac_mcp.mcp.view_pictogram import view


def _texts(result) -> str:
    return "\n".join(part.text for part in result.content if part.type == "text")


# --------------------------------------------------------------------------- #
# search_pictograms
# --------------------------------------------------------------------------- #


def test_search_empty_query(catalog: Catalog) -> None:
    assert search(catalog, "   ") == "Empty search query."


def test_search_no_match(catalog: Catalog) -> None:
    message = search(catalog, "Zebra")
    assert "No pictograms found" in message
    assert "Zebra" in message


def test_search_reports_word_matches(catalog: Catalog) -> None:
    message = search(catalog, "Auto", limit=5)
    assert message.startswith('Found: 2 matches for "Auto":')
    assert "Auto (KFZ)" in message
    assert "2_Auto.png" not in message


def test_search_respects_limit(catalog: Catalog) -> None:
    assert search(catalog, "Auto", limit=1).count("\n") == 1


# --------------------------------------------------------------------------- #
# view_pictogram
# --------------------------------------------------------------------------- #


def test_view_with_output_returns_url_not_image(catalog: Catalog, output_dir: Path) -> None:
    result = view(catalog, "Auto", output_dir)

    types = [part.type for part in result]
    assert types == ["text", "text"]
    assert result[0].text == 'Show "Auto (KFZ)" (synonyms: KFZ)'
    assert result[1].text.startswith("Image: http")
    assert result[1].text.endswith(".png")
    assert any(path.name.endswith("2_Auto.png") for path in output_dir.iterdir())


def test_view_without_output_returns_image_block(catalog: Catalog) -> None:
    result = view(catalog, "Regen", None)
    assert result[0].type == "text"
    assert hasattr(result[1], "data")  # an MCP image content object


def test_view_unknown_word_raises(catalog: Catalog) -> None:
    with pytest.raises(KeyError):
        view(catalog, "Zebra", None)


# --------------------------------------------------------------------------- #
# render_pictogram_sheet
# --------------------------------------------------------------------------- #


def test_render_word_sheet_requires_words(catalog: Catalog, output_dir: Path) -> None:
    with pytest.raises(ValueError, match="words must not be empty"):
        render_word_sheet(catalog, [], output_dir=output_dir)


def test_render_word_sheet_requires_parallel_roles(catalog: Catalog, output_dir: Path) -> None:
    with pytest.raises(ValueError, match="same length"):
        render_word_sheet(catalog, ["Regen", "rot"], roles=["NOUN"], output_dir=output_dir)


def test_render_word_sheet_rejects_invalid_role(catalog: Catalog, output_dir: Path) -> None:
    with pytest.raises(ValueError, match="Invalid role"):
        render_word_sheet(catalog, ["Regen"], roles=["NOPE"], output_dir=output_dir)


def test_render_word_sheet_saves_and_returns_url(catalog: Catalog, output_dir: Path) -> None:
    result = render_word_sheet(
        catalog,
        ["Regen", "rot"],
        roles=["NOUN", "QUALITY"],
        sentence="Test",
        output_dir=output_dir,
    )

    text = _texts(result)
    assert "Rendered pictogram sheet: Regen, rot" in text
    assert "File: " in text
    assert "Image: http" in text
    assert [part.type for part in result.content] == ["text"]
    assert result.structured_content is None
    assert list(output_dir.glob("sheet_*.png"))


def test_render_word_sheet_without_output_returns_image(catalog: Catalog) -> None:
    result = render_word_sheet(catalog, ["Regen"], output_dir=None)
    assert [part.type for part in result.content] == ["text", "image"]


def test_render_word_sheet_accepts_lowercase_roles(catalog: Catalog, output_dir: Path) -> None:
    result = render_word_sheet(catalog, ["Regen"], roles=["noun"], output_dir=output_dir)
    assert "Rendered pictogram sheet: Regen" in _texts(result)


# --------------------------------------------------------------------------- #
# render_pictogram_layout
# --------------------------------------------------------------------------- #


def test_render_tree_requires_layout_object(catalog: Catalog, output_dir: Path) -> None:
    with pytest.raises(ValueError, match="layout must be"):
        render_tree(catalog, ["not", "a", "dict"], output_dir=output_dir)  # type: ignore[arg-type]


def test_render_tree_renders_grid(catalog: Catalog, output_dir: Path) -> None:
    result = render_tree(
        catalog,
        {
            "type": "grid",
            "columns": ["Tag"],
            "rows": [{"header": "1.", "cells": ["Regen", None]}],
        },
        output_dir=output_dir,
    )

    text = _texts(result)
    assert "Rendered pictogram layout" in text
    assert "Image: http" in text
    assert list(output_dir.glob("sheet_*.png"))


def test_render_tree_rejects_invalid_role(catalog: Catalog, output_dir: Path) -> None:
    with pytest.raises(ValueError, match="Invalid role"):
        render_tree(
            catalog,
            {"type": "icon", "word": "Regen", "role": "NOPE"},
            output_dir=output_dir,
        )


def test_render_tree_unknown_word_raises(catalog: Catalog, output_dir: Path) -> None:
    with pytest.raises(KeyError):
        render_tree(catalog, {"type": "icon", "word": "Zebra"}, output_dir=output_dir)


def test_render_tree_invalid_page_size_raises(catalog: Catalog, output_dir: Path) -> None:
    with pytest.raises(ValueError, match="Seitengr"):
        render_tree(
            catalog,
            {"type": "icon", "word": "Regen"},
            page_size="huge",
            output_dir=output_dir,
        )
