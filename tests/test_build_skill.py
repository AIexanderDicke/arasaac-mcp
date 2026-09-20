"""The skill generator (:mod:`scripts.build_skill`).

``scripts/prompt.md`` is the single source of truth; these tests pin the split
into skill/recipe files and, importantly, fail if the generated files on disk
drift from the source.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    path = REPO_ROOT / "scripts" / "build_skill.py"
    spec = importlib.util.spec_from_file_location("build_skill", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def build_skill() -> ModuleType:
    return _load()


def test_parse_sections_finds_title_and_numbered_sections(build_skill: ModuleType) -> None:
    title, sections = build_skill.parse_sections(
        (REPO_ROOT / "scripts" / "prompt.md").read_text(encoding="utf-8")
    )
    assert title
    assert set(sections) >= {0, 1, 2, 3, 4, 5, 9, 10, 11, 12, 13, 14}
    assert sections[0].startswith("## 0.")


def test_require_missing_section_exits(build_skill: ModuleType) -> None:
    with pytest.raises(SystemExit):
        build_skill._require({}, 99)


def test_build_files_returns_skill_and_recipe_parts(build_skill: ModuleType) -> None:
    files = build_skill.build_files()
    assert set(files) == {
        "skills/arasaac/SKILL.md",
        "arasaac_mcp/recipe/core.md",
        "arasaac_mcp/recipe/workflow.md",
        "arasaac_mcp/recipe/design.md",
        "arasaac_mcp/recipe/layouts.md",
        "arasaac_mcp/recipe/contract.md",
        "arasaac_mcp/recipe/sources.md",
    }


def test_generated_skill_is_thin_with_frontmatter(build_skill: ModuleType) -> None:
    skill = build_skill.build_files()["skills/arasaac/SKILL.md"]
    assert skill.startswith("---\nname: arasaac\n")
    assert "allowed-tools:" in skill
    assert "Do not edit by hand" in skill
    assert "arasaac://rules" in skill
    assert "Antworte immer auf Deutsch" in skill


def test_generated_recipe_parts_carry_the_marker(build_skill: ModuleType) -> None:
    files = build_skill.build_files()
    for relative, content in files.items():
        if relative.endswith("SKILL.md"):
            continue
        assert "Do not edit by hand" in content


def test_generated_files_match_prompt_source(build_skill: ModuleType) -> None:
    """Regression: the committed skill/recipe files must not drift."""
    for relative, content in build_skill.build_files().items():
        on_disk = REPO_ROOT / relative
        assert on_disk.is_file(), f"missing generated file: {relative}"
        assert on_disk.read_text(encoding="utf-8") == content, f"stale generated file: {relative}"


def test_check_passes_on_the_repo(build_skill: ModuleType, capsys) -> None:
    assert build_skill.main(["--check"]) == 0
    assert "up to date" in capsys.readouterr().out


def test_main_writes_and_checks_in_a_temp_root(
    build_skill: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = REPO_ROOT / "scripts" / "prompt.md"
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "prompt.md").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.setattr(build_skill, "ROOT", tmp_path)
    monkeypatch.setattr(build_skill, "SOURCE", scripts / "prompt.md")
    monkeypatch.setattr(build_skill, "SKILL_DIR", tmp_path / "skills" / "arasaac")
    monkeypatch.setattr(build_skill, "RECIPE_DIR", tmp_path / "arasaac_mcp" / "recipe")

    assert build_skill.main([]) == 0
    assert (tmp_path / "skills" / "arasaac" / "SKILL.md").is_file()
    assert build_skill.main(["--check"]) == 0

    (tmp_path / "arasaac_mcp" / "recipe" / "core.md").write_text("stale", encoding="utf-8")
    assert build_skill.main(["--check"]) == 1
