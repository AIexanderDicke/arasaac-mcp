# ARASAAC pictogram sheets

Turn German text — a sentence, a situation, a rule, a routine or a request —
into a clear sequence of [ARASAAC](https://arasaac.org) pictograms and render it
as an image or PDF. The strip is meant to be understood **at a glance**, so
people with limited reading or language comprehension — especially children in
special education — can follow it without reading the words.

A model (provided by the host, not by this project) works out the core message
and picks the pictograms; these tools resolve German **words** to icons and draw
them. The same logic is available in three forms:

- **MCP server** (`arasaac-mcp`) — four word-based tools for any MCP-capable
  host: search, view, render a strip, render a free layout.
- **CLI** (`make-sheet`) — render a strip or layout directly from files or JSON.
- **Agent Skill** — the transcriber recipe, generated from `scripts/prompt.md`.

## Learn more

- [`CONCEPT.md`](CONCEPT.md) — idea, background, AAC research and roadmap.
- [`AGENTS.md`](AGENTS.md) — setup, usage, architecture and internals.
- [`scripts/prompt.md`](scripts/prompt.md) — the rules the model follows.

ARASAAC pictograms are licensed **CC BY-NC-SA**; the renderer keeps an
attribution footer. See [`CONCEPT.md`](CONCEPT.md).
