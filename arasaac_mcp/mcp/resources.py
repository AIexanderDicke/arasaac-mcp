"""The MCP prompt and resources: the recipe and the generated Agent Skill.

``scripts/prompt.md`` is the single source of truth; the thin generated
``SKILL.md`` is served verbatim, and the packaged recipe parts
(``arasaac_mcp/recipe/``) are each served as their own resource so hosts load
recipe parts on demand.
"""

from __future__ import annotations

from pathlib import Path

from ..skill import recipe_paths, rules_text, skill_markdown
from ._deps import FastMCP


def _register_part(server: "FastMCP", path: Path) -> None:
    """Register one recipe part as ``arasaac://rules/<stem>``."""

    @server.resource(
        f"arasaac://rules/{path.stem}",
        name=f"arasaac {path.stem}",
        description=f"Transcriber recipe part ({path.stem}).",
        mime_type="text/markdown",
    )
    def part_resource() -> str:
        """One recipe part, loaded on demand."""
        return path.read_text(encoding="utf-8")


def register(server: "FastMCP") -> None:
    """Register the prompt and the resources on ``server``."""

    @server.prompt(
        name="pictogram_transcriber",
        description="The full ARASAAC transcriber recipe plus the German text to depict.",
    )
    def pictogram_transcriber(text: str) -> str:
        """Apply the pictogram recipe to a German text and depict its content."""
        return (
            f"{rules_text()}\n\n---\n\n"
            f"Transcribe the following German text into pictograms:\n\n{text}"
        )

    @server.resource(
        "arasaac://skill",
        name="arasaac skill",
        description="The arasaac Agent Skill (SKILL.md, thin entry point).",
        mime_type="text/markdown",
    )
    def skill_resource() -> str:
        """The Agent Skill definition."""
        return skill_markdown() or rules_text()

    @server.resource(
        "arasaac://rules",
        name="arasaac rules",
        description="The full transcriber recipe (all parts in one document).",
        mime_type="text/markdown",
    )
    def rules_resource() -> str:
        """The complete recipe."""
        return rules_text()

    for path in recipe_paths():
        _register_part(server, path)
