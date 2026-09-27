# ARASAAC MCP

An MCP server that lets an agent turn a text (a sentence, a situation, a
rule, a routine or a request) into a sequence of
[ARASAAC](https://arasaac.org) pictograms and render it as an image. The
strip is meant to be understood **at a glance**, so people with limited reading
or language comprehension (especially children in special education) can follow
it without reading the words.

## Restrictions

- Currently focused on **German only**.
- The MCP server only returns a **link**, which hosts such as the ChatGPT
  Desktop App render as a preview. MCP Apps are not supported right now.

The Docker image ships only the ~9 MB word index (`metadata_de.json`), not the
~338 MB pictogram set: a pictogram is fetched from ARASAAC on first use and
cached (offline runs can pre-populate the cache and set `ARASAAC_FETCH=off`).

## Run MCP Server from Docker

Run the MCP server (streamable HTTP on `/mcp`), with a named volume so
the pictograms fetched on first use survive the container:

```bash
docker run --rm -p 8000:8000 -v arasaac-cache:/app/cache -e ARASAAC_TRANSPORT=http -e ARASAAC_HOST=0.0.0.0 -e ARASAAC_PORT=8000 -e ARASAAC_PUBLIC_BASE_URL=http://localhost:8000 ghcr.io/aiexanderdicke/arasaac-mcp:main
```
Point the MCP host at `http://localhost:8000/mcp`.

## Optional: generate icon descriptions

`scripts/generate_icon_descriptions.py` asks a vision model to write a structured
description for every pictogram. These descriptions are the basis for a better,
description-based search (plan:
[`docs/optimized-search.md`](docs/optimized-search.md)).

- **Output:** `icons/descriptions/<lang>/[id]_description.json` — one
  JSON file per icon and language (default `en`; add German with `--lang en de`).
- **Cached & resumable:** an existing non-empty file is skipped, so you can stop
  and re-run to continue; `--force` regenerates. `--dry-run` lists the files
  without calling the API.

Each record has this structure (content fields are written in `<lang>`):

```json
{
  "id": 2239,
  "filename": "2239_Biene.png",
  "description": "What is concretely visible in the schematic image.",
  "usage": "When to use it and what it explicitly does NOT stand for.",
  "synonyms": ["bee", "honeybee"]
}
```

| Field | Meaning |
| --- | --- |
| `id` | ARASAAC pictogram id — the stable, language-independent key (same id across languages). |
| `filename` | Language-specific PNG file name; kept for traceability. |
| `description` | What is visible in the image. |
| `usage` | Context and disambiguation (when to use it, what it does not mean). |
| `synonyms` | Fitting words/synonyms in the record's language. |

```bash
export OPENROUTER_API_KEY=sk-or-...

# Trial 50 icons (English by default), then drop --limit for the full set
uv run python scripts/generate_icon_descriptions.py --limit 50 \
  --model google/gemini-2.5-flash-lite --workers 4
```

Model choice: `google/gemini-2.5-flash-lite` is the recommended balance of
quality and price, `qwen/qwen3.7-flash` is the cheapest solid option, and
`qwen/qwen3.8-27b:free` is free for a small trial. The script default is
`deepseek/deepseek-v4-flash-vision-exp`; override it with `--model` (any
OpenAI-compatible vision endpoint works via `--base-url` / `--api-key`).

## License & attribution

This project uses the pictograms of [ARASAAC](https://arasaac.org) (the Aragonese
Portal of Augmentative and Alternative Communication), created by the Government
of Aragón. They are licensed **CC BY-NC-SA** (attribution, non-commercial,
share-alike). 
