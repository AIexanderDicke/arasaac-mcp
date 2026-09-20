"""Word-based catalog: search, resolution and the lazy-fetch policy."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers import build_icons_dir, make_png

from arasaac_mcp.catalog import (
    VALID_ROLES,
    Catalog,
    Pictogram,
    default_icons_dir,
    get_catalog,
)

# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _label_of_line(line: str) -> str:
    return line.split(". ", 1)[1].split(" — ")[0].strip()


def _labels(lines: list[str]) -> list[str]:
    return [_label_of_line(line) for line in lines]


# --------------------------------------------------------------------------- #
# indexing
# --------------------------------------------------------------------------- #


def test_pictures_index_metadata_entries(catalog: Catalog) -> None:
    by_file = {pic.file: pic for pic in catalog.pictures}
    assert by_file["1_Regen.png"].keywords == ("Regen",)
    assert by_file["1_Regen.png"].pic_id == 1
    assert by_file["1_Regen.png"].extra == ("Wetter", "Natur")
    assert by_file["2_Auto.png"].keywords == ("Auto", "KFZ")


def test_pictures_include_unindexed_files(catalog: Catalog) -> None:
    by_file = {pic.file: pic for pic in catalog.pictures}
    assert by_file["999_unlisted.png"].keywords == ()
    assert by_file["999_unlisted.png"].pic_id == 999
    assert by_file["orphan.png"].pic_id is None


@pytest.mark.regression
@pytest.mark.xfail(
    reason="With metadata_de.json present, files that do not match "
    "[id]_[description].png are added to the index twice: once by the "
    "metadata branch and again via the `unindexed` list appended afterwards.",
)
def test_unindexed_file_is_indexed_once(catalog: Catalog) -> None:
    files = [pic.file for pic in catalog.pictures]
    assert files.count("orphan.png") == 1


def test_index_falls_back_to_filenames_without_metadata(tmp_path: Path) -> None:
    icons = tmp_path / "icons"
    icons.mkdir()
    make_png(icons / "3123_Regen.png")
    make_png(icons / "no_id.png")

    catalog = Catalog(icons)

    by_file = {pic.file: pic for pic in catalog.pictures}
    assert by_file["3123_Regen.png"].desc == "Regen"
    assert by_file["3123_Regen.png"].pic_id == 3123
    assert by_file["no_id.png"].pic_id is None
    assert catalog.search_lines("Regen", 5)


def test_missing_icons_dir_yields_empty_catalog(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path / "does-not-exist")
    assert catalog.pictures == []
    assert catalog.search("Regen") == []
    assert catalog.search_lines("Regen") == []


def test_metadata_entry_without_id_is_skipped(tmp_path: Path) -> None:
    icons = tmp_path / "icons"
    icons.mkdir()
    (icons / "metadata_de.json").write_text(
        json.dumps(
            [
                {"keywords": [{"keyword": "ohne Id"}]},
                {"_id": 2, "keywords": [{"keyword": "Berg"}]},
            ]
        ),
        encoding="utf-8",
    )
    make_png(icons / "2_Berg.png")

    catalog = Catalog(icons)

    assert {pic.file for pic in catalog.pictures} == {"2_Berg.png"}


def test_metadata_only_catalog_resolves_to_fetchable_id(tmp_path: Path) -> None:
    icons = tmp_path / "icons"
    icons.mkdir()
    (icons / "metadata_de.json").write_text(
        json.dumps([{"_id": 1, "keywords": [{"keyword": "Regen"}]}]), encoding="utf-8"
    )

    catalog = Catalog(icons)
    pic = catalog.resolve("Regen")

    assert pic.file == "1_Regen.png"
    assert pic.pic_id == 1
    with pytest.raises(FileNotFoundError):
        catalog.ensure(pic)


# --------------------------------------------------------------------------- #
# word / label logic
# --------------------------------------------------------------------------- #


def test_word_of_prefers_first_keyword_else_description(catalog: Catalog) -> None:
    regen = catalog.resolve("Regen")
    unlisted = next(pic for pic in catalog.pictures if pic.file == "999_unlisted.png")
    assert catalog.word_of(regen) == "Regen"
    assert catalog.word_of(unlisted) == "unlisted"


def test_label_of_unique_word_is_plain(catalog: Catalog) -> None:
    assert catalog.label_of(catalog.resolve("Regen")) == "Regen"


def test_label_of_shared_word_adds_unique_synonym(catalog: Catalog) -> None:
    labels = {catalog.label_of(pic) for pic in catalog.pictures if pic.keywords[:1] == ("Auto",)}
    assert labels == {"Auto (KFZ)", "Auto (Wagen)"}


def test_label_of_shared_word_without_unique_synonym_stays_shared(catalog: Catalog) -> None:
    labels = {catalog.label_of(pic) for pic in catalog.pictures if pic.keywords[:1] == ("Schüler",)}
    assert labels == {"Schüler"}


def test_labels_never_expose_ids_or_filenames(catalog: Catalog) -> None:
    for line in catalog.search_lines("Auto", 10) + catalog.search_lines("Regen", 10):
        assert "_" not in line.split(" — ")[0]
        assert not any(char.isdigit() for char in _label_of_line(line))


# --------------------------------------------------------------------------- #
# search
# --------------------------------------------------------------------------- #


def test_search_finds_the_exact_word_first(catalog: Catalog) -> None:
    lines = catalog.search_lines("Regen", 5)
    assert lines[0].startswith("1. Regen")


def test_search_surfaces_synonyms(catalog: Catalog) -> None:
    lines = catalog.search_lines("KFZ", 5)
    assert any("Auto" in line for line in lines)


def test_search_matches_tags(catalog: Catalog) -> None:
    labels = _labels(catalog.search_lines("Fahrzeug", 5))
    assert labels == ["Auto (KFZ)", "Auto (Wagen)"]


def test_search_forgives_plural_stem(catalog: Catalog) -> None:
    assert _labels(catalog.search_lines("rotes", 5)) == ["rot"]


def test_search_matches_prefix_and_substring(catalog: Catalog) -> None:
    assert _labels(catalog.search_lines("Reg", 5)) == ["Regen"]
    assert _labels(catalog.search_lines("egen", 5)) == ["Regen"]


def test_search_matches_description_of_unindexed_file(catalog: Catalog) -> None:
    assert _labels(catalog.search_lines("unlisted", 5)) == ["unlisted"]


def test_search_requires_all_tokens(catalog: Catalog) -> None:
    assert catalog.search_lines("Auto Zebra", 5) == []
    assert _labels(catalog.search_lines("Auto Fahrzeug", 5)) == ["Auto (KFZ)", "Auto (Wagen)"]


def test_search_empty_and_whitespace_query(catalog: Catalog) -> None:
    assert catalog.search("") == []
    assert catalog.search("   ") == []
    assert catalog.search_lines("") == []


def test_search_no_match(catalog: Catalog) -> None:
    assert catalog.search_lines("Zebra", 5) == []


def test_search_dedupes_shared_labels(catalog: Catalog) -> None:
    labels = _labels(catalog.search_lines("Schüler", 5))
    assert labels == ["Schüler"]


def test_search_limit_is_bounded(catalog: Catalog) -> None:
    assert len(catalog.search("Auto", limit=1)) == 1
    assert len(catalog.search("Auto", limit=0)) == 1
    assert len(catalog.search("Auto", limit=-5)) == 1
    assert len(catalog.search("Auto", limit=10_000)) <= len(catalog.pictures)


@pytest.mark.parametrize("query", ["Regen", "Auto", "Schüler", "rot", "Berg", "KFZ", "Fahrzeug"])
def test_search_labels_round_trip(catalog: Catalog, query: str) -> None:
    for line in catalog.search_lines(query, 12):
        label = _label_of_line(line)
        assert catalog.label_of(catalog.resolve(label)) == label


# --------------------------------------------------------------------------- #
# resolve
# --------------------------------------------------------------------------- #


def test_resolve_plain_and_qualified(catalog: Catalog) -> None:
    assert catalog.resolve("Auto").file == "2_Auto.png"
    assert catalog.resolve("Auto (Wagen)").file == "3_Auto.png"


def test_resolve_is_case_insensitive(catalog: Catalog) -> None:
    assert catalog.resolve("regen").file == catalog.resolve("REGEN").file


def test_resolve_fuzzy_fallback(catalog: Catalog) -> None:
    assert catalog.resolve("Autos").file == "2_Auto.png"
    assert catalog.resolve("Reg").file == "1_Regen.png"


def test_resolve_unknown_raises_keyerror(catalog: Catalog) -> None:
    with pytest.raises(KeyError, match="Zebra"):
        catalog.resolve("Zebra")
    with pytest.raises(KeyError):
        catalog.resolve("")


def test_resolve_prefers_the_candidate_with_the_plain_label(tmp_path: Path) -> None:
    icons = tmp_path / "icons"
    icons.mkdir()
    (icons / "metadata_de.json").write_text(
        json.dumps(
            [
                {"_id": 1, "keywords": [{"keyword": "Auto"}, {"keyword": "KFZ"}]},
                {"_id": 2, "keywords": [{"keyword": "Auto"}]},
            ]
        ),
        encoding="utf-8",
    )
    make_png(icons / "1_Auto.png")
    make_png(icons / "2_Auto.png")

    catalog = Catalog(icons)
    # The shared word forces a qualifier on id 1; the plain id 2 must win.
    assert catalog.label_of(catalog.resolve("Auto")) == "Auto"
    assert catalog.resolve("Auto").file == "2_Auto.png"
    assert catalog.resolve("Auto (KFZ)").file == "1_Auto.png"


def test_resolve_is_deterministic(catalog: Catalog) -> None:
    files = {catalog.resolve("Auto").file for _ in range(5)}
    assert files == {"2_Auto.png"}


# --------------------------------------------------------------------------- #
# ensure / path_of
# --------------------------------------------------------------------------- #


def test_ensure_returns_the_local_file(catalog: Catalog, icons_dir: Path) -> None:
    pic = catalog.resolve("Regen")
    assert catalog.ensure(pic) == icons_dir / pic.file


def test_ensure_without_fetch_raises(catalog: Catalog) -> None:
    pic = catalog.resolve("Regen")
    (catalog.icons_dir / pic.file).unlink()

    with pytest.raises(FileNotFoundError, match="not available locally"):
        catalog.ensure(pic)


def test_ensure_without_id_raises_even_when_fetching(tmp_path: Path) -> None:
    icons = tmp_path / "icons"
    icons.mkdir()
    orphan = make_png(icons / "orphan.png")
    catalog = Catalog(icons, fetch_missing=True)
    pic = catalog.resolve("orphan")
    orphan.unlink()  # the local file wins; only a missing one may be fetched

    with pytest.raises(FileNotFoundError, match="no ARASAAC id"):
        catalog.ensure(pic)


def test_ensure_fetches_into_the_cache_and_is_then_local(tmp_path: Path) -> None:
    icons = tmp_path / "icons"
    icons.mkdir()
    (icons / "metadata_de.json").write_text(
        json.dumps([{"_id": 42, "keywords": [{"keyword": "Regen"}]}]), encoding="utf-8"
    )
    static = tmp_path / "static"
    source = make_png(static / "42" / "42_500.png")
    cache = tmp_path / "cache"

    catalog = Catalog(icons, cache_dir=cache, fetch_missing=True, static_url=static.as_uri())
    pic = catalog.resolve("Regen")
    first = catalog.ensure(pic)
    second = catalog.ensure(pic)

    assert first == cache / pic.file
    assert first.read_bytes() == source.read_bytes()
    assert second == first
    assert not (icons / pic.file).exists(), "bundled icons dir must stay untouched"


def test_ensure_prefers_cache_over_icons_dir(tmp_path: Path) -> None:
    icons = build_icons_dir(tmp_path / "library")
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "1_Regen.png").write_bytes(b"cached")
    catalog = Catalog(icons, cache_dir=cache, fetch_missing=True)

    assert catalog.ensure(catalog.resolve("Regen")) == cache / "1_Regen.png"


def test_path_of_and_resolve_file_agree(catalog: Catalog) -> None:
    assert catalog.path_of("Regen") == catalog.resolve_file("Regen")
    assert catalog.path_of("Regen") == catalog.ensure(catalog.resolve("Regen"))


def test_ensure_reports_a_fetch_failure_as_filenotfound(tmp_path: Path) -> None:
    icons = tmp_path / "icons"
    icons.mkdir()
    (icons / "metadata_de.json").write_text(
        json.dumps([{"_id": 42, "keywords": [{"keyword": "Regen"}]}]), encoding="utf-8"
    )
    catalog = Catalog(
        icons,
        cache_dir=tmp_path / "cache",
        fetch_missing=True,
        static_url=(tmp_path / "empty-static").as_uri(),
    )

    with pytest.raises(FileNotFoundError, match="could not fetch"):
        catalog.ensure(catalog.resolve("Regen"))


# --------------------------------------------------------------------------- #
# layout nodes
# --------------------------------------------------------------------------- #


def test_icon_node_resolves_word_to_file_and_concept(catalog: Catalog) -> None:
    node = catalog.icon_node("Regen")
    assert node["type"] == "icon"
    assert node["file"].endswith("1_Regen.png")
    assert node["concept"] == "Regen"


def test_resolve_layout_node_string_becomes_icon(catalog: Catalog) -> None:
    node = catalog.resolve_layout_node("Regen")
    assert node["type"] == "icon"
    assert node["concept"] == "Regen"
    assert "word" not in node


def test_resolve_layout_node_list_becomes_column(catalog: Catalog) -> None:
    node = catalog.resolve_layout_node(["Regen", "Berg"])
    assert node["type"] == "column"
    assert [child["concept"] for child in node["children"]] == ["Regen", "Berg"]


def test_resolve_layout_node_keeps_explicit_file_and_concept(catalog: Catalog) -> None:
    node = catalog.resolve_layout_node({"type": "icon", "word": "Regen", "file": "x.png"})
    assert node["file"] == "x.png"
    assert node["concept"] == "Regen"
    assert "word" not in node


def test_resolve_layout_node_text_suppresses_concept(catalog: Catalog) -> None:
    node = catalog.resolve_layout_node({"type": "icon", "word": "Regen", "text": "eigener Text"})
    assert node["text"] == "eigener Text"
    assert "concept" not in node


def test_resolve_layout_node_normalises_roles(catalog: Catalog) -> None:
    node = catalog.resolve_layout_node({"type": "icon", "word": "Regen", "role": "noun"})
    assert node["role"] == "NOUN"


def test_resolve_layout_node_rejects_invalid_role(catalog: Catalog) -> None:
    with pytest.raises(ValueError, match="Invalid role"):
        catalog.resolve_layout_node({"type": "icon", "word": "Regen", "role": "NOPE"})


@pytest.mark.parametrize("role", VALID_ROLES)
def test_resolve_layout_node_accepts_every_valid_role(catalog: Catalog, role: str) -> None:
    node = catalog.resolve_layout_node({"type": "icon", "word": "Regen", "role": role})
    assert node["role"] == role


def test_resolve_layout_node_recurses_children_items_child_and_node(catalog: Catalog) -> None:
    children = catalog.resolve_layout_node({"type": "row", "children": ["Regen"]})
    items = catalog.resolve_layout_node({"type": "row", "items": ["Regen"]})
    child = catalog.resolve_layout_node({"type": "card", "child": "Regen"})
    node = catalog.resolve_layout_node({"type": "canvas", "children": [{"x": 5, "node": "Regen"}]})

    assert children["children"][0]["concept"] == "Regen"
    assert items["items"][0]["concept"] == "Regen"
    assert child["child"]["concept"] == "Regen"
    assert node["children"][0]["node"]["concept"] == "Regen"


def test_resolve_layout_node_keeps_grid_cell_positions(catalog: Catalog) -> None:
    node = catalog.resolve_layout_node(
        {"type": "grid", "columns": ["A"], "rows": [{"cells": [None, "Regen"]}]}
    )
    cells = node["rows"][0]["cells"]
    assert cells[0] is None
    assert cells[1]["concept"] == "Regen"


@pytest.mark.regression
@pytest.mark.xfail(
    reason="The layout engine treats an empty-string grid cell as empty "
    "(layout._cell_node), but catalog.resolve_layout_node resolves it as a "
    "word and raises KeyError before rendering.",
)
def test_resolve_layout_node_empty_cell_string_is_empty(catalog: Catalog) -> None:
    node = catalog.resolve_layout_node(
        {"type": "grid", "columns": ["A"], "rows": [{"cells": [""]}]}
    )
    assert node["rows"][0]["cells"][0] in (None, "")


def test_resolve_layout_node_grid_columns_stay_labels(catalog: Catalog) -> None:
    node = catalog.resolve_layout_node({"type": "grid", "columns": ["Montag"], "rows": []})
    assert node["columns"] == ["Montag"]


def test_resolve_layout_node_top_level_cells(catalog: Catalog) -> None:
    node = catalog.resolve_layout_node({"type": "grid", "cells": [None, "Regen"]})
    assert node["cells"][0] is None
    assert node["cells"][1]["concept"] == "Regen"


def test_resolve_layout_node_rows_scalar_is_preserved(catalog: Catalog) -> None:
    node = catalog.resolve_layout_node({"type": "grid", "rows": ["raw"]})
    assert node["rows"] == ["raw"]


def test_resolve_layout_node_rows_as_list_of_lists(catalog: Catalog) -> None:
    node = catalog.resolve_layout_node({"type": "grid", "rows": [["Regen", None]]})
    assert node["rows"][0]["cells"][0]["concept"] == "Regen"
    assert node["rows"][0]["cells"][1] is None


def test_resolve_layout_node_none_and_type_errors(catalog: Catalog) -> None:
    assert catalog.resolve_layout_node(None) is None
    with pytest.raises(TypeError):
        catalog.resolve_layout_node(42)


def test_resolve_layout_node_unknown_word_raises(catalog: Catalog) -> None:
    with pytest.raises(KeyError):
        catalog.resolve_layout_node({"type": "icon", "word": "Zebra"})


# --------------------------------------------------------------------------- #
# default_icons_dir / get_catalog
# --------------------------------------------------------------------------- #


def test_default_icons_dir_prefers_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_icons = tmp_path / "env-icons"
    env_icons.mkdir()
    monkeypatch.setenv("ARASAAC_ICONS_DIR", str(env_icons))

    assert default_icons_dir(tmp_path) == env_icons


def test_default_icons_dir_falls_back_to_cwd_and_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ARASAAC_ICONS_DIR", raising=False)
    project = tmp_path / "project"
    (project / "icons").mkdir(parents=True)
    nested = project / "sub"
    nested.mkdir()

    # No <nested>/icons, so the parent's icons directory is used.
    assert default_icons_dir(nested) == project / "icons"


def test_default_icons_dir_returns_cwd_icons_when_nothing_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ARASAAC_ICONS_DIR", raising=False)
    assert default_icons_dir(tmp_path) == tmp_path / "icons"


def test_get_catalog_caches_by_key(tmp_path: Path) -> None:
    icons = build_icons_dir(tmp_path / "library")

    first = get_catalog(icons)
    second = get_catalog(icons)
    other = get_catalog(icons, fetch_missing=True)

    assert first is second
    assert first is not other


def test_pictogram_is_hashable_value_object() -> None:
    left = Pictogram("a.png", "A", ("A",))
    right = Pictogram("a.png", "A", ("A",))
    assert left == right
    assert hash(left) == hash(right)
