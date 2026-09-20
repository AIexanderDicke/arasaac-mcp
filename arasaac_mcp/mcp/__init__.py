"""MCP server: ARASAAC pictogram tools for any MCP-capable host.

The host brings the model.  This server only exposes the deterministic
capability — word search, visual inspection and rendering — so no API key or LLM
runs here.  The recipe (how to pick and order pictograms) ships as an MCP prompt
and as the ``arasaac`` Agent Skill; the essential operational rules
are also in the tool descriptions, which every host puts in context.

Each tool lives in its own module (one file per tool):

===========================================  =================================================
Tool                                          Module
===========================================  =================================================
``search_pictograms``                         :mod:`.search_pictograms`
``view_pictogram``                            :mod:`.view_pictogram`
``render_pictogram_sheet``                    :mod:`.render_pictogram_sheet`
``render_pictogram_layout``                   :mod:`.render_pictogram_layout`
prompt ``pictogram_transcriber`` + resources  :mod:`.resources`
``GET /sheet/<name>``                         :mod:`.routes`
===========================================  =================================================

The word logic lives in :mod:`arasaac_mcp.catalog`; this package only
registers tools and shapes their results.
"""

from __future__ import annotations

from .server import create_server, main

__all__ = ["create_server", "main"]
