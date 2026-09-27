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

RECORD = {
    "description": "Eine Biene sammelt Nektar.",
    "usage": "Für das Insekt Biene; nicht für andere Insekten.",
    "synonyms": ["Honigbiene", "Imme"],
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
    content = json.dumps(data if data is not None else RECORD, ensure_ascii=False)
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


def test_target_path_uses_lang_and_id(gen: ModuleType, tmp_path: Path) -> None:
    assert gen.target_path(tmp_path, "de", 2239) == tmp_path / "de" / "2239_description.json"
    assert gen.target_path(tmp_path, "en", 2239) == tmp_path / "en" / "2239_description.json"


# 2 -------------------------------------------------------------------------
def test_build_prompt_mentions_schematic_and_fields(gen: ModuleType) -> None:
    context = {"keywords": ["Biene"], "tags": ["insekt"], "categories": ["tier"]}
    prompt = gen.build_prompt("Biene", context, "en")
    assert '"Biene"' in prompt
    assert "English" in prompt
    assert "schematic" in prompt
    assert "insekt" in prompt
    for field in ("description", "usage", "synonyms"):
        assert field in prompt
    assert "file name" in prompt  # explicitly forbids filename references
    # discourage the boilerplate openings and the "how it is drawn" description
    assert "do not start with boilerplate" in prompt
    assert "WHAT is depicted" in prompt


def test_build_record_has_id_and_content(gen: ModuleType) -> None:
    record = gen.build_record(RECORD, 2239)
    assert record == {
        "id": 2239,
        "description": "Eine Biene sammelt Nektar.",
        "usage": "Für das Insekt Biene; nicht für andere Insekten.",
        "synonyms": ["Honigbiene", "Imme"],
    }
    assert "2239" not in record["description"]


def test_build_record_accepts_verwendung_alias(gen: ModuleType) -> None:
    record = gen.build_record({"description": "x", "verwendung": "y", "synonyms": []}, 1)
    assert record["usage"] == "y"


# 3 -------------------------------------------------------------------------
def test_parse_model_response_plain_content(gen: ModuleType) -> None:
    assert gen.parse_model_response(_fake_body())["description"] == "Eine Biene sammelt Nektar."


def test_parse_model_response_fenced_block(gen: ModuleType) -> None:
    content = "```json\n" + json.dumps(RECORD, ensure_ascii=False) + "\n```"
    body = json.dumps({"choices": [{"message": {"content": content}}]})
    assert gen.parse_model_response(body)["synonyms"] == ["Honigbiene", "Imme"]


def test_parse_model_response_raises_on_invalid(gen: ModuleType) -> None:
    with pytest.raises(ValueError):
        gen.parse_model_response("not json at all")


def test_request_description_sets_headers_and_endpoint(
    gen: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    class _Response:
        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def read(self) -> bytes:
            return b"{}"

    def fake_urlopen(request: object, timeout: float = 0) -> _Response:
        captured["request"] = request
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    gen.request_description(
        b"png",
        "prompt",
        model="m",
        base_url="https://openrouter.ai/api/v1",
        api_key="k",
        timeout=1,
    )

    request = captured["request"]
    assert request.full_url == "https://openrouter.ai/api/v1/chat/completions"  # type: ignore[attr-defined]
    user_agent = request.get_header("User-agent")  # type: ignore[attr-defined]
    assert user_agent and "arasaac" in user_agent.lower()
    assert request.get_header("X-title") == gen.APP_TITLE  # type: ignore[attr-defined]
    payload = json.loads(request.data)  # type: ignore[attr-defined]
    assert payload["response_format"]["type"] == "json_schema"
    assert set(payload["response_format"]["json_schema"]["schema"]["properties"]) == {
        "description",
        "usage",
        "synonyms",
    }


def test_request_description_can_omit_schema(
    gen: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    class _Response:
        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def read(self) -> bytes:
            return b"{}"

    def fake_urlopen(request: object, timeout: float = 0) -> _Response:
        captured["request"] = request
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    gen.request_description(
        b"png",
        "prompt",
        model="m",
        base_url="https://x.test",
        api_key="k",
        timeout=1,
        use_schema=False,
    )
    payload = json.loads(captured["request"].data)  # type: ignore[attr-defined]
    assert "response_format" not in payload


# 4 -------------------------------------------------------------------------
def test_collect_targets_skip_force_limit_langs(gen: ModuleType, tmp_path: Path) -> None:
    icons = _write_icons(tmp_path)
    out = icons / "descriptions"
    (out / "de").mkdir(parents=True)
    (out / "de" / "2239_description.json").write_text("{}", encoding="utf-8")

    ids = [(t.pic_id, t.lang) for t in gen.collect_targets(icons, out, ["de"])]
    assert ids == [(3151, "de"), (10147, "de")]

    multi = [(t.pic_id, t.lang) for t in gen.collect_targets(icons, out, ["de", "en"])]
    assert (2239, "en") in multi
    assert (2239, "de") not in multi

    forced = [(t.pic_id, t.lang) for t in gen.collect_targets(icons, out, ["de"], force=True)]
    assert forced == [(2239, "de"), (3151, "de"), (10147, "de")]

    limited = gen.collect_targets(icons, out, ["de", "en"], force=True, limit=1)
    assert {(t.pic_id, t.lang) for t in limited} == {(2239, "de"), (2239, "en")}


# 5 -------------------------------------------------------------------------
def test_main_writes_json_and_second_run_skips(
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
    out = icons / "descriptions" / "en"
    record = json.loads((out / "2239_description.json").read_text(encoding="utf-8"))
    assert record["id"] == 2239
    assert record["description"] == "Eine Biene sammelt Nektar."
    assert "filename" not in record
    assert (out / "10147_description.json").is_file()
    assert len(calls) == 3

    calls.clear()
    assert gen.main(argv) == 0
    assert calls == []


def test_main_generates_multiple_languages(
    gen: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    icons = _write_icons(tmp_path)
    calls: list[str] = []

    def fake(image_bytes: bytes, prompt: str, **kwargs: object) -> str:
        calls.append(prompt)
        return _fake_body()

    monkeypatch.setattr(gen, "request_description", fake)
    argv = ["--icons-dir", str(icons), "--api-key", "test", "--lang", "de", "en"]

    assert gen.main(argv) == 0
    assert (icons / "descriptions" / "de" / "2239_description.json").is_file()
    assert (icons / "descriptions" / "en" / "2239_description.json").is_file()
    assert len(calls) == 6


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
    assert not (icons / "descriptions" / "en" / "2239_description.json").exists()


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
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert gen.main(["--icons-dir", str(icons), "--api-key", ""]) == 2
