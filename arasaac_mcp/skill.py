"""Locate and read the ``arasaac`` Agent Skill and the recipe resources.

The thin skill is generated into ``skills/arasaac/`` by ``scripts/build_skill.py``;
the recipe parts it points at are generated into ``arasaac_mcp/recipe/`` (inside
the package, so an installed wheel keeps them) and served as MCP resources.
``scripts/prompt.md`` remains the single source of truth.
"""

from __future__ import annotations

import os
from pathlib import Path

SKILL_NAME = "arasaac"
_REPO_ROOT = Path(__file__).resolve().parents[1]


def skill_dir() -> Path | None:
    """Find the skill directory, or ``None`` when it is not available."""
    candidates: list[Path] = []
    env = os.environ.get("ARASAAC_SKILL_DIR")
    if env:
        candidates.append(Path(env))
    candidates.append(_REPO_ROOT / "skills" / SKILL_NAME)
    candidates.append(Path.cwd() / "skills" / SKILL_NAME)
    for candidate in candidates:
        if (candidate / "SKILL.md").is_file():
            return candidate
    return None


def skill_markdown() -> str:
    """Return ``SKILL.md`` (empty string when the skill is not installed)."""
    directory = skill_dir()
    if directory is None:
        return ""
    return (directory / "SKILL.md").read_text(encoding="utf-8")


def recipe_paths() -> list[Path]:
    """All recipe parts inside the package, sorted by name."""
    directory = _REPO_ROOT / "arasaac_mcp" / "recipe"
    return sorted(directory.glob("*.md"))


def rules_text() -> str:
    """The full recipe.

    ``scripts/prompt.md`` is the single source of truth; without it (installed
    wheel), the packaged recipe parts are joined, and without those an embedded
    minimal summary keeps the MCP prompt working.
    """
    prompt = _REPO_ROOT / "scripts" / "prompt.md"
    if prompt.is_file():
        return prompt.read_text(encoding="utf-8").strip()

    parts = [path.read_text(encoding="utf-8").strip() for path in recipe_paths()]
    if parts:
        return "\n\n---\n\n".join(parts)

    return _FALLBACK_RULES


_FALLBACK_RULES = """\
# ARASAAC pictograms

Antworte immer auf Deutsch. Search and refer to pictograms by German **word**
only (never ids or file names). Work out the core message (a request is not the
message), drop function words, choose concrete icons, verify ambiguous words
with `view_pictogram`, keep the sequence short (≤ ~8), and render it once with
`render_pictogram_sheet` or `render_pictogram_layout`."""
