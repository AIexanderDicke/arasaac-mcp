"""Server-wide instructions put in context by every MCP host."""

from __future__ import annotations

INSTRUCTIONS = """\
Turn German text into ARASAAC pictograms. Address pictograms by German **word**
only — the tools resolve words to images and never expose ids or file names.
Work out the core message first (a request for a picture is satisfied by
depicting its content, not the request), drop function words, choose concrete
icons, verify ambiguous candidates with view_pictogram, keep the sequence short
(aim ≤ 5, hard cap ~8) and render it once. Reply in German. See the
`pictogram_transcriber` prompt for the full rules.\
"""
