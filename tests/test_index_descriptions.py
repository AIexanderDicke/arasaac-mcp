"""The Qdrant ingest script (:mod:`scripts.index_descriptions`), offline.

The database is Qdrant's in-process local mode and the embedder is the
deterministic :class:`HashingEmbedder`; ``main`` runs with both injected.
"""

from __future__ import annotations

import importlib.util
import json
import types
from pathlib import Path
from types import ModuleType

import pytest
from helpers import HashingEmbedder, build_icons_dir
from qdrant_client import QdrantClient

pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect in the local Qdrant")

REPO_ROOT = Path(__file__).resolve().parents[1]

DESCRIPTIONS = {
    1: ("Rain falling from clouds over a meadow.", "Weather, not shower.", ["rain", "wet"]),
    2: ("A red car driving on a country road.", "Vehicle on road, not toy.", ["car"]),
    6: ("A red circle on white ground.", "Colour red.", ["red"]),
}


def _load() -> ModuleType:
    path = REPO_ROOT / "scripts" / "index_descriptions.py"
    spec = importlib.util.spec_from_file_location("index_descriptions", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script() -> ModuleType:
    return _load()


@pytest.fixture
def icons_dir(tmp_path: Path) -> Path:
    return build_icons_dir(tmp_path)


@pytest.fixture
def descriptions_file(tmp_path: Path, icons_dir: Path) -> Path:
    path = tmp_path / "descriptions.jsonl"
    lines = [
        json.dumps(
            {
                "id": pic_id,
                "description": description,
                "usage": usage,
                "synonyms": synonyms,
            }
        )
        for pic_id, (description, usage, synonyms) in DESCRIPTIONS.items()
    ]
    lines.append(json.dumps({"id": 9999, "description": "Unknown icon."}))
    lines.append("not json")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


@pytest.fixture
def memory_index(monkeypatch: pytest.MonkeyPatch, script: ModuleType) -> object:
    """Replace :meth:`VectorIndex.open` with an in-process database."""
    from arasaac_mcp.vector import VectorIndex

    holder = types.SimpleNamespace(index=None)

    def open_memory(url=None, collection=None):
        if holder.index is not None and (
            collection is None or holder.index.collection == collection
        ):
            return holder.index
        index = VectorIndex(QdrantClient(":memory:"), collection or "script_col")
        holder.index = index
        return index

    monkeypatch.setattr(script.VectorIndex, "open", staticmethod(open_memory))
    return holder  # type: ignore[return-value]


@pytest.fixture
def offline_env(script: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ARASAAC_EMBED_BATCH_SIZE",):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(script, "make_embedder", lambda *a, **k: HashingEmbedder())
    monkeypatch.setenv("ARASAAC_QDRANT_URL", "http://offline-test")


# -- record loading -------------------------------------------------------


def test_load_jsonl_skips_bad_lines(script: ModuleType, descriptions_file: Path) -> None:
    records = script.load_jsonl_records(descriptions_file)
    assert {record["id"] for record in records} == {1, 2, 6, 9999}


def test_load_dir_records_flat_and_nested(tmp_path: Path, script: ModuleType) -> None:
    (tmp_path / "en").mkdir()
    (tmp_path / "en" / "5_description.json").write_text(
        json.dumps({"id": 5, "description": "A pupil.", "synonyms": []}), encoding="utf-8"
    )
    (tmp_path / "7_description.json").write_text(
        json.dumps({"id": 7, "description": "A mountain."}), encoding="utf-8"
    )
    (tmp_path / "garbage.json").write_text("{}", encoding="utf-8")
    records = script.load_dir_records(tmp_path, "*.json")
    assert {record["id"] for record in records} == {5, 7}


def test_build_records_joins_metadata(
    script: ModuleType, icons_dir: Path, descriptions_file: Path
) -> None:
    from arasaac_mcp.catalog import Catalog

    catalog = Catalog(icons_dir)
    metadata = script.load_metadata(icons_dir)
    records, skipped = script.build_records(
        catalog, metadata, script.load_jsonl_records(descriptions_file)
    )
    assert skipped == 1  # id 9999 has no icon
    by_id = {record.pic_id: record for record in records}
    assert by_id[1].word == "Regen"
    assert by_id[1].tags == ("Wetter",)
    assert by_id[2].label == "Auto (KFZ)"
    assert by_id[2].synonyms == ("car",)
    assert by_id[6].keywords == ("rot",)


def test_build_records_without_metadata_tags(
    script: ModuleType, icons_dir: Path, descriptions_file: Path
) -> None:
    from arasaac_mcp.catalog import Catalog

    records, _ = script.build_records(
        Catalog(icons_dir), {}, script.load_jsonl_records(descriptions_file)
    )
    assert all(record.tags == () and record.categories == () for record in records)


# -- main() end to end -----------------------------------------------------


def _argv(
    icons_dir: Path,
    descriptions_file: Path,
    collection: str = "script_col",
    extra: list[str] | None = None,
) -> list[str]:
    return [
        "--qdrant-url",
        "http://offline-test",
        "--collection",
        collection,
        "--icons-dir",
        str(icons_dir),
        "--descriptions-file",
        str(descriptions_file),
        "--embed-provider",
        "openai",
    ] + (extra or [])


def test_main_dry_run_writes_nothing(
    script: ModuleType,
    capsys: pytest.CaptureFixture,
    offline_env,
    icons_dir: Path,
    descriptions_file: Path,
) -> None:
    exit_code = script.main(_argv(icons_dir, descriptions_file, extra=["--dry-run"]))
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "pictograms to index" in output
    assert "dry run" in output


def test_main_ingests_and_resumes(
    script: ModuleType,
    memory_index,
    offline_env,
    icons_dir: Path,
    descriptions_file: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    exit_code = script.main(_argv(icons_dir, descriptions_file))
    assert exit_code == 0
    index = memory_index.index
    assert index.count() == 3
    assert index.existing_ids() == {1, 2, 6}

    exit_code = script.main(_argv(icons_dir, descriptions_file))
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "points to ingest   : 0" in output
    assert index.count() == 3


def test_main_force_and_recreate(
    script: ModuleType, memory_index, offline_env, icons_dir: Path, descriptions_file: Path, capsys
) -> None:
    script.main(_argv(icons_dir, descriptions_file))
    exit_code = script.main(_argv(icons_dir, descriptions_file, extra=["--force"]))
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "points to ingest   : 3" in output

    exit_code = script.main(_argv(icons_dir, descriptions_file, extra=["--recreate"]))
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "created collection" in output


def test_main_limit(
    script: ModuleType, memory_index, offline_env, icons_dir: Path, descriptions_file: Path
) -> None:
    exit_code = script.main(_argv(icons_dir, descriptions_file, extra=["--limit", "1"]))
    assert exit_code == 0
    assert memory_index.index.count() == 1


def test_main_dimension_mismatch_reports(
    script: ModuleType,
    memory_index,
    offline_env,
    icons_dir: Path,
    descriptions_file: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    from arasaac_mcp.vector import VectorIndex

    pre = VectorIndex(QdrantClient(":memory:"), "script_col")
    pre.ensure_collection(8)

    original_open = script.VectorIndex.open

    def open_presized(url=None, collection=None):
        return pre

    monkey_open = open_presized
    script.VectorIndex.open = staticmethod(monkey_open)  # type: ignore[method-assign]
    try:
        exit_code = script.main(_argv(icons_dir, descriptions_file))
    finally:
        script.VectorIndex.open = original_open  # type: ignore[method-assign]
    output = capsys.readouterr()
    assert exit_code == 1
    assert "--recreate" in output.err


def test_main_without_descriptions_reported(
    script: ModuleType,
    memory_index,
    offline_env,
    icons_dir: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    with pytest.raises(SystemExit) as raised:
        script.main(
            [
                "--qdrant-url",
                "http://offline-test",
                "--icons-dir",
                str(icons_dir),
                "--descriptions-file",
                str(icons_dir / "missing.jsonl"),
            ]
        )
    output = capsys.readouterr()
    assert raised.value.code == 2
    assert "description source not found" in output.err
