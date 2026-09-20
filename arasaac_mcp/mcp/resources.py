"""The MCP prompt and resources: the recipe and the generated Agent Skill.

``scripts/prompt.md`` is the single source of truth; the generated skill in
``skills/`` is served verbatim.
"""

from __future__ import annotations

from ..skill import rules_text, skill_markdown
from ._deps import FastMCP


def register(server: "FastMCP") -> None:
    """Register the prompt and the two resources on ``server``."""

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
        description="The arasaac Agent Skill (SKILL.md).",
        mime_type="text/markdown",
    )
    def skill_resource() -> str:
        """The Agent Skill definition."""
        return skill_markdown() or rules_text()

    @server.resource(
        "arasaac://rules",
        name="arasaac rules",
        description="The full transcriber recipe (skill plus references).",
        mime_type="text/markdown",
    )
    def rules_resource() -> str:
        """The complete recipe."""
        return rules_text()
