"""Locating and reading the Agent Skill and recipe (:mod:`arasaac_mcp.skill`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from arasaac_mcp import skill


def test_skill_dir_finds_the_generated_skill(repo_root: Path) -> None:
    directory = skill.skill_dir()
    assert directory == repo_root / "skills" / "arasaac"
    assert (directory / "SKILL.md").is_file()


def test_skill_dir_honours_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    override = tmp_path / "custom-skill"
    override.mkdir()
    (override / "SKILL.md").write_text("custom", encoding="utf-8")
    monkeypatch.setenv("ARASAAC_SKILL_DIR", str(override))

    assert skill.skill_dir() == override


def test_skill_dir_returns_none_when_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ARASAAC_SKILL_DIR", raising=False)
    monkeypatch.setattr(skill, "_REPO_ROOT", tmp_path / "empty")
    monkeypatch.chdir(tmp_path)

    assert skill.skill_dir() is None


def test_skill_markdown_contains_frontmatter() -> None:
    markdown = skill.skill_markdown()
    assert "name: arasaac" in markdown
    assert "allowed-tools:" in markdown


def test_skill_markdown_empty_without_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ARASAAC_SKILL_DIR", raising=False)
    monkeypatch.setattr(skill, "_REPO_ROOT", tmp_path / "empty")
    monkeypatch.chdir(tmp_path)

    assert skill.skill_markdown() == ""


def test_recipe_paths_are_sorted_markdown_parts() -> None:
    paths = skill.recipe_paths()
    assert paths, "packaged recipe parts must exist"
    assert paths == sorted(paths)
    assert all(path.suffix == ".md" for path in paths)
    assert {path.stem for path in paths} >= {
        "core",
        "workflow",
        "design",
        "layouts",
        "contract",
        "sources",
    }


def test_rules_text_prefers_the_source_prompt(repo_root: Path) -> None:
    prompt = (repo_root / "scripts" / "prompt.md").read_text(encoding="utf-8").strip()
    assert skill.rules_text() == prompt


def test_rules_text_joins_packaged_parts_without_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recipe = tmp_path / "arasaac_mcp" / "recipe"
    recipe.mkdir(parents=True)
    (recipe / "a.md").write_text("part a", encoding="utf-8")
    (recipe / "b.md").write_text("part b", encoding="utf-8")
    monkeypatch.setattr(skill, "_REPO_ROOT", tmp_path)

    assert skill.rules_text() == "part a\n\n---\n\npart b"


def test_rules_text_falls_back_to_embedded_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(skill, "_REPO_ROOT", tmp_path)

    assert "Antworte immer auf Deutsch" in skill.rules_text()
