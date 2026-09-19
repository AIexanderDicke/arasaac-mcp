"""Locate and read the ``arasaac-pictograms`` Agent Skill.

The skill files are generated from ``scripts/prompt.md`` by ``scripts/build_skill.py``.
The MCP server reuses them as its prompt and resource, so the recipe has exactly
one source of truth.
"""

from __future__ import annotations

import os
from pathlib import Path

SKILL_NAME = "arasaac-pictograms"
_REPO_ROOT = Path(__file__).resolve().parents[2]


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


def reference_paths() -> list[Path]:
    """All reference documents, sorted by name."""
    directory = skill_dir()
    if directory is None:
        return []
    return sorted((directory / "references").glob("*.md"))


def rules_text() -> str:
    """The full recipe: ``SKILL.md`` followed by every reference document.

    Falls back to ``scripts/prompt.md`` and finally to an embedded minimal summary, so
    the MCP prompt keeps working in an installed wheel.
    """
    directory = skill_dir()
    if directory is not None:
        parts = [(directory / "SKILL.md").read_text(encoding="utf-8").strip()]
        for path in reference_paths():
            parts.append(path.read_text(encoding="utf-8").strip())
        return "\n\n---\n\n".join(parts)

    prompt = _REPO_ROOT / "scripts" / "prompt.md"
    if prompt.is_file():
        return prompt.read_text(encoding="utf-8").strip()

    return _FALLBACK_RULES


_FALLBACK_RULES = """\
# ARASAAC pictograms

Antworte immer auf Deutsch. Search and refer to pictograms by German **word**
only (never ids or file names). Work out the core message (a request is not the
message), drop function words, choose concrete icons, verify ambiguous words
with `view_pictogram`, keep the sequence short (≤ ~8), and render it once with
`render_pictogram_sheet` or `render_pictogram_layout`."""
