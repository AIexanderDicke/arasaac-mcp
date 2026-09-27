"""The icon-description generator (:mod:`scripts.generate_icon_descriptions`).

Everything runs offline: ``request_description`` is monkeypatched, so no HTTP
call is ever made.  The module is loaded from its path because ``scripts/`` is
not an importable package (same pattern as ``test_download_icons.py``).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

DESCRIPTION = {
    "description": "Eine Biene sammelt Nektar.",
    "visual": "Gelb-schwarzes Insekt mit Flügeln.",
    "usage": "Zeigt das Insekt Biene.",
    "synonyms": ["Honigbiene", "Imme"],
    "caveats": None,
}

METADATA = [
    {"_id": 2239, "keywords": [{"keyword": "Biene"}], "tags": ["insekt"], "categories": ["tier"]},
    {
        "_id": 3151,
        "keywords": [{"keyword": "Auto"}],
        "tags": ["fahrzeug"],
        "categories": ["verkehr"],
    },
    {
        "_id": 10147,
        "keywords": [{"keyword": "Toilettenpapier"}],
        "tags": ["bad"],
        "categories": ["hygiene"],
    },
]


def _load() -> ModuleType:
    path = REPO_ROOT / "scripts" / "generate_icon_descriptions.py"
    spec = importlib.util.spec_from_file_location("generate_icon_descriptions", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def gen() -> ModuleType:
    return _load()


def _write_icons(
    root: Path,
    names: tuple[str, ...] = (
        "2239_Biene.png",
        "3151_Auto.png",
        "10147_Toilettenpapier_abreißen.png",
    ),
) -> Path:
    icons = root / "icons"
    icons.mkdir(parents=True, exist_ok=True)
    for name in names:
        (icons / name).write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (icons / "metadata_de.json").write_text(
        json.dumps(METADATA, ensure_ascii=False), encoding="utf-8"
    )
    return icons


def _fake_body(data: dict | None = None) -> str:
    content = json.dumps(data if data is not None else DESCRIPTION, ensure_ascii=False)
    return json.dumps({"choices": [{"message": {"content": content}}]}, ensure_ascii=False)


# 1 -------------------------------------------------------------------------
def test_parse_icon_filename(gen: ModuleType) -> None:
    assert gen.parse_icon_filename("2239_Biene.png") == (2239, "Biene")
    assert gen.parse_icon_filename("10147_Toilettenpapier_abreißen.png") == (
        10147,
        "Toilettenpapier_abreißen",
    )
    assert gen.parse_icon_filename("orphan.png") is None
    assert gen.parse_icon_filename("metadata_de.json") is None


def test_target_path_md_and_txt(gen: ModuleType, tmp_path: Path) -> None:
    assert gen.target_path(tmp_path, 2239, "Biene", "md") == tmp_path / "2239_Biene_description.md"
    assert gen.target_path(tmp_path, 2239, "Biene", "txt") == (
        tmp_path / "2239_Biene_description.txt"
    )


# 2 -------------------------------------------------------------------------
def test_build_prompt_mentions_name_and_lang(gen: ModuleType) -> None:
    context = {"keywords": ["Biene"], "tags": ["insekt"], "categories": ["tier"]}
    prompt = gen.build_prompt("Biene", 2239, context, "de")
    assert "Biene" in prompt
    assert "de" in prompt
    assert "Deutsch" in prompt
    assert "insekt" in prompt


def test_render_description_markdown(gen: ModuleType) -> None:
    body = gen.render_description(DESCRIPTION, 2239, "Biene", "md")
    assert body.startswith("# Biene (ARASAAC 2239)")
    for heading in (
        "## Gezeigt im Bild",
        "## Bedeutung und Verwendung",
        "## Synonyme und Stichwörter",
        "## Hinweise",
    ):
        assert heading in body
    assert "Eine Biene sammelt Nektar." in body
    assert "Honigbiene" in body


def test_render_description_txt_has_no_hash(gen: ModuleType) -> None:
    body = gen.render_description(DESCRIPTION, 2239, "Biene", "txt")
    assert "#" not in body
    assert "Biene" in body
    assert "Gezeigt im Bild" in body
    assert "Imme" in body


# 3 -------------------------------------------------------------------------
def test_parse_model_response_plain_content(gen: ModuleType) -> None:
    assert gen.parse_model_response(_fake_body())["description"] == "Eine Biene sammelt Nektar."


def test_parse_model_response_fenced_block(gen: ModuleType) -> None:
    content = "```json\n" + json.dumps(DESCRIPTION, ensure_ascii=False) + "\n```"
    body = json.dumps({"choices": [{"message": {"content": content}}]})
    assert gen.parse_model_response(body)["synonyms"] == ["Honigbiene", "Imme"]


def test_parse_model_response_raises_on_invalid(gen: ModuleType) -> None:
    with pytest.raises(ValueError):
        gen.parse_model_response("not json at all")


# 4 -------------------------------------------------------------------------
def test_collect_targets_skip_force_limit(gen: ModuleType, tmp_path: Path) -> None:
    icons = _write_icons(tmp_path)
    out = icons / "descriptions"
    out.mkdir()
    (out / "2239_Biene_description.md").write_text("done", encoding="utf-8")

    ids = [t.pic_id for t in gen.collect_targets(icons, out, "md")]
    assert ids == [3151, 10147]

    forced = [t.pic_id for t in gen.collect_targets(icons, out, "md", force=True)]
    assert forced == [2239, 3151, 10147]

    limited = gen.collect_targets(icons, out, "md", force=True, limit=1)
    assert [t.pic_id for t in limited] == [2239]
    assert gen.collect_targets(icons, out, "md", limit=1)[0].pic_id == 3151


# 5 -------------------------------------------------------------------------
def test_main_writes_and_second_run_skips(
    gen: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    icons = _write_icons(tmp_path)
    calls: list[str] = []

    def fake(image_bytes: bytes, prompt: str, **kwargs: object) -> str:
        calls.append(prompt)
        return _fake_body()

    monkeypatch.setattr(gen, "request_description", fake)
    argv = ["--icons-dir", str(icons), "--api-key", "test", "--workers", "3"]

    assert gen.main(argv) == 0
    out = icons / "descriptions"
    for name in ("2239_Biene_description.md", "3151_Auto_description.md"):
        assert (out / name).is_file()
    assert (out / "10147_Toilettenpapier_abreißen_description.md").is_file()
    assert len(calls) == 3

    calls.clear()
    assert gen.main(argv) == 0
    assert calls == []


# 6 -------------------------------------------------------------------------
def test_main_reports_failure_without_partial_file(
    gen: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    icons = _write_icons(tmp_path, names=("2239_Biene.png",))

    def fake(image_bytes: bytes, prompt: str, **kwargs: object) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(gen, "request_description", fake)
    rc = gen.main(["--icons-dir", str(icons), "--api-key", "x", "--workers", "1", "--retries", "0"])
    assert rc == 1
    assert not (icons / "descriptions" / "2239_Biene_description.md").exists()


# 7 -------------------------------------------------------------------------
def test_dry_run_makes_no_calls_and_writes_nothing(
    gen: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    icons = _write_icons(tmp_path)

    def fake(image_bytes: bytes, prompt: str, **kwargs: object) -> str:
        raise AssertionError("request_description must not be called in dry-run")

    monkeypatch.setattr(gen, "request_description", fake)
    assert gen.main(["--icons-dir", str(icons), "--dry-run"]) == 0
    out = icons / "descriptions"
    assert not out.exists() or not any(out.iterdir())


# 8 -------------------------------------------------------------------------
def test_missing_api_key_returns_2(
    gen: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    icons = _write_icons(tmp_path)
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    assert gen.main(["--icons-dir", str(icons), "--api-key", ""]) == 2
