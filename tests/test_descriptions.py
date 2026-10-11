"""The description loader (:mod:`arasaac_mcp.descriptions`)."""

from __future__ import annotations

import json
from pathlib import Path

from arasaac_mcp.descriptions import (
    DescriptionRecord,
    description_for,
    find_source,
    load_descriptions,
)


def test_find_source_prefers_the_jsonl(tmp_path: Path) -> None:
    icons = tmp_path / "icons"
    icons.mkdir()
    (icons / "descriptions.jsonl").write_text("{}\n", encoding="utf-8")
    (icons / "descriptions").mkdir()
    assert find_source(icons) == icons / "descriptions.jsonl"


def test_find_source_prefers_language_dir(tmp_path: Path) -> None:
    icons = tmp_path / "icons"
    (icons / "descriptions" / "en").mkdir(parents=True)
    (icons / "descriptions" / "de").mkdir(parents=True)
    assert find_source(icons) == icons / "descriptions" / "en"
    assert find_source(icons, lang="de") == icons / "descriptions" / "de"


def test_find_source_absent(tmp_path: Path) -> None:
    assert find_source(tmp_path) is None


def test_load_from_jsonl_skips_bad_records(tmp_path: Path) -> None:
    icons = tmp_path / "icons"
    icons.mkdir()
    (icons / "descriptions.jsonl").write_text(
        "\n".join(
            (
                json.dumps(
                    {
                        "id": 7,
                        "description": "A mountain.",
                        "usage": "Hiking.",
                        "synonyms": ["berg"],
                    }
                ),
                "{}",
                '{"id": "no", "description": "x"}',
                '{"id": 9, "description": "   "}',
                "not json at all",
                "",
            )
        ),
        encoding="utf-8",
    )
    records = load_descriptions(icons)
    assert set(records) == {7}
    assert records[7].synonyms == ("berg",)
    assert records[7].usage == "Hiking."


def test_load_absent_safe(tmp_path: Path) -> None:
    assert load_descriptions(tmp_path / "does-not-exist") == {}
    empty = tmp_path / "empty"
    empty.mkdir()
    assert load_descriptions(empty) == {}


def test_load_from_directory_layout(tmp_path: Path) -> None:
    icons = tmp_path / "icons"
    (icons / "descriptions" / "en").mkdir(parents=True)
    (icons / "descriptions" / "en" / "7_description.json").write_text(
        json.dumps({"id": 7, "description": "A mountain."}), encoding="utf-8"
    )
    records = load_descriptions(icons)
    assert set(records) == {7}


def test_load_from_flat_legacy_directory(tmp_path: Path) -> None:
    """The pre-per-language flat layout (``<dir>/[id]_description.json``) works."""
    icons = tmp_path / "icons"
    (icons / "descriptions").mkdir(parents=True)
    (icons / "descriptions" / "5_description.json").write_text(
        json.dumps({"id": 5, "description": "Rain."}), encoding="utf-8"
    )
    records = load_descriptions(icons)
    assert set(records) == {5}


def test_description_for(tmp_path: Path) -> None:
    icons = tmp_path / "icons"
    icons.mkdir()
    (icons / "descriptions.jsonl").write_text(
        json.dumps({"id": 7, "description": "A mountain.", "synonyms": ["berg"]}),
        encoding="utf-8",
    )
    record = description_for(7, icons)
    assert record is not None
    assert record.text == "A mountain. berg"
    assert description_for(None) is None
    assert description_for(9999, icons) is None


def test_records_are_hashable_value_objects() -> None:
    left = DescriptionRecord(1, "a", "", ())
    right = DescriptionRecord(1, "a", "", ())
    assert left == right
