# Optimized search — LLM icon descriptions + retrieval

*Giving every pictogram a rich, LLM-written structured description and
searching over it — so the word layer
[`arasaac_mcp/catalog.py`](../arasaac_mcp/catalog.py) finds the right icon from a
natural request instead of from terse ARASAAC keywords alone.*

## 1. Goal and problem

The model addresses pictograms **only by words** ([`AGENTS.md`](../AGENTS.md),
“The agent tool contract is WORD-BASED”; [`scripts/prompt.md`](../scripts/prompt.md)
§3). `catalog.py` maps those words to files, so retrieval quality is bounded by
the word layer.

Today that layer is purely **lexical over ARASAAC keywords/tags**:
`_tokenize` (regex `[^\W_]+`, lower-cased) feeds `_score`, which gives a keyword
exact match 6, a prefix 4, a `desc` substring 3, an arbitrary keyword substring
2 and a tag/category substring 1, with a small per-keyword penalty. Every token
must match somewhere (**AND**); `search` → `_dedupe_by_label` → `search_lines`
returns word-only lines. The metadata is terse and sometimes misleading — the
same traps catalogued in [`icon-descriptions.md`](icon-descriptions.md) §1
(`verbleiben`, `vor`, `stehen`, `Auto`, `Schüler`) are invisible to `_score`,
because nothing but the keyword strings is available.

**Goal:** a richer description per icon (generated once, offline, by a
vision-language model) plus a **retrieval layer over those descriptions**, while
every existing invariant of the word layer holds unchanged. Concretely:

1. Each pictogram gets a structured JSON description (per language) in a
   per-icon file.
2. `catalog.py` searches those descriptions in addition to the existing
   keywords/tags, ranking them with a hybrid lexical score.
3. Optionally, an offline semantic embedding re-ranks the lexical candidates.
4. The model keeps seeing **words only** — the description never leaks an id or
   a filename.

This is the retrieval counterpart to [`icon-descriptions.md`](icon-descriptions.md),
which plans *curated* words, and [`multilingual.md`](multilingual.md), which
makes the layer language-parameterised. The generated descriptions are the
**data** those plans can later consume.

## 2. Plan

Each phase is independently shippable; phases 2–5 are **doc-only for now** and
Phase 1 is being implemented.

### Phase 1 — Generate descriptions (implemented)

A stdlib-only batch script sends each icon PNG to a vision model and writes a
structured JSON record, one file per icon and language, to
`<out-dir>/<lang>/[id]_description.json`. Full interface in §3.

- Files: `scripts/generate_icon_descriptions.py` (new).
- Tests: unit tests over a mocked/injected HTTP layer (no network): filename
  derivation, cache-hit skipping, `--force`, atomic write, exit codes, missing
  API key, multi-language output.
- Exit criteria: a dry run plans one output per `[id]_[name].png` and language;
  a rerun skips existing non-empty files; interrupting and resuming produces the
  full set.

### Phase 2 — Load/index descriptions

A small, Pillow-free and network-free module turns the description directory
into an in-memory `pic_id` → record mapping, per language.

- Files: `arasaac_mcp/descriptions.py` (new).
- API sketch (frozen defaults keep callers valid):
  - `load_descriptions(descriptions_dir: Path, lang: str) -> dict[int, dict]`
    keyed by the numeric `pic_id`, skipping missing/empty files.
  - `Descriptions.for_pictogram(pic: Pictogram) -> dict | None` resolves by
    `pic.pic_id` (falling back to the file stem), or `None`.
  - The record is the JSON object: `id`, `description`, `usage`, `synonyms`
    (see §3). Consumers key on the language-independent `id`; the model never
    sees it and never writes an id or file name into the content fields.
- Behaviour: **absent-safe** — a missing directory, missing entry or empty file
  yields an empty mapping, never an error. Reads text only; no PNG, no network.
  The directory defaults to `<icons-dir>/descriptions/<lang>` (optionally
  `ARASAAC_DESCRIPTIONS_DIR`), discovered like `default_icons_dir`.
- Tests: `tests/test_descriptions.py` — load over a synthetic directory;
  absent-safe; id and file-stem mapping; non-empty filter.
- Exit criteria: descriptions load for the test fixtures; with no description
  directory the mapping is empty and no existing test changes.

### Phase 3 — Hybrid lexical retrieval (SQLite FTS5)

Extend the search path in `catalog.py` with a full-text index over description +
keywords + tags + `desc`, ranked by FTS5 BM25 and blended with the existing
`_score`.

- Files: `arasaac_mcp/catalog.py` (owner; a small stdlib-only helper such as
  `arasaac_mcp/fts.py` is allowed if it keeps the file focused).
- Index: a virtual table
  `fts5(pic_id UNINDEXED, text, tokenize='unicode61 remove_diacritics 0')`, one
  row per indexed `Pictogram` (`text` = description + keywords + tags + `desc`).
  Rows are built from metadata even when **no** description exists, so a
  metadata-only index is unchanged.
- Query: build the FTS5 `MATCH` from `_tokenize(query)` as an OR of prefix
  terms, take the candidates, then keep the existing **AND** `_score > 0`
  filter. Final rank blends the base score with a normalized BM25 term
  (`bm25()` is negative-is-better), e.g. `_score + w * normalize(-bm25)`, with a
  small default `w` tuned on the §5 evaluation set.
- Determinism: a fixed `ORDER BY` tie-break on `_natural_key(pic.file)` (then
  `pic_id`) so equal scores never reorder between runs; the result shape and
  `search_lines` output stay exactly as today (word-only labels).
- Fallback: if `descriptions.py` yields nothing, or `sqlite3`/FTS5 is
  unavailable, `search`/`resolve` behave byte-identically to today’s `_score`
  path. The index is cached per icons directory alongside `_INDEX_CACHE`.
- Tests: a parity test (no descriptions ⇒ identical ordering to the current
  implementation), a description-boost test (a tied candidate whose description
  names a synonym rises), round-trip preserved, AND preserved, deterministic
  repeated calls, and a guard/skip when FTS5 is missing.
- Exit criteria: all existing catalog tests pass unchanged; new tests green;
  the metadata-only catalog still resolves.

### Phase 4 — Optional semantic embeddings

A semantic re-rank is an **optional enhancement**, never a dependency, and
**lexical stays primary** (semantics only re-order the lexical candidates).

- Hard constraint: neither the default provider (OpenRouter) nor OpenCode Zen
  exposes an `/embeddings` endpoint, so embeddings need a **configurable
  OpenAI-compatible endpoint** (base URL + model + key via env, e.g.
  `ARASAAC_EMBED_*`) **or a local model**.
- Offline build: a batch script computes one vector per description (and embeds
  the query at eval/request time) into a compact artifact, stored Python-stdlib
  only (`array`/`struct`, no `numpy` — `numpy` is not a core dependency). Shape:
  `embeddings.f32` plus a small `embeddings.json` manifest:
  ```json
  {
    "model": "text-embedding-3-small",
    "dim": 1536,
    "pic_ids": [2239, 2339, 3123]
  }
  ```
- Runtime: `catalog.py` stays **network-free**, so it cannot embed the query
  itself. The caller (the MCP layer, which may use the network) supplies the
  query vector, or a local model is used; either way the core only reads the
  on-disk artifact. No artifact ⇒ pure lexical ordering, unchanged.
- Tests: exact lexical ordering without the artifact; reordering only within the
  lexical candidate set when it is present; malformed/missing artifact ignored.
- Exit criteria: with no artifact, Phase 3 behaviour is reproduced exactly.

### Phase 5 — Tool surface + evaluation

- `search_pictograms` (`arasaac_mcp/mcp/search_pictograms.py`) keeps its
  `(query, limit)` signature; the only optional change is a richer word-only
  detail line (e.g. a synonym drawn from the description). No ids, filenames or
  `structuredContent` ever reach the model.
- An **offline German evaluation set** — queries paired with the expected
  pictogram (`pic_id`/word) — is added and run as a regression test.
- Metrics: **top-1 accuracy**, **MRR**, **ambiguous-hit rate** and **wrong-hit
  rate**. Thresholds are pinned in the test so a retrieval regression fails CI.
- Files: `arasaac_mcp/mcp/search_pictograms.py`, `tests/` (evaluation +
  threshold test), possibly `scripts/eval_search.py`.
- Exit criteria: the frozen evaluation set meets its pinned thresholds, the
  label round-trip holds over every result, and no test exposes an id or a
  filename.

## 3. Phase 1 script reference

`scripts/generate_icon_descriptions.py` — batch LLM description generator
(**stdlib only**). It sends each icon image to an OpenAI-compatible
vision/chat endpoint and writes one structured JSON record per icon **and
language** (default `en`; add German with `--lang en de`). The English prompt
asks for what is depicted (not how it is drawn) and for the usage without
boilerplate openings, forbids filename/ID references in the content, and a
`json_schema` `response_format` enforces the shape.

### Record structure

One file per icon and language, `<lang>/[id]_description.json`:

```json
{
  "id": 2239,
  "description": "A bee, shown from the side.",
  "usage": "Represents the insect bee (animals, nature, apiculture); not other insects and not honey.",
  "synonyms": ["bee", "honeybee"]
}
```

| Field | Type | Written by | Meaning |
| --- | --- | --- | --- |
| `id` | number | script | ARASAAC pictogram id — the **stable, language-independent key** and the only reference to the icon. Verified: `de`, `en` and `es` expose the exact same 13,827 ids, and the PNG URL (`pictograms/<id>/<id>_<size>.png`) depends only on the id. |
| `description` | string | model | What is depicted, as a reader would name the subject/scene — one concise sentence (e.g. `"A sidewalk of a street viewed from a slightly elevated angle."`). Not a breakdown of how the drawing is composed. |
| `usage` | string | model | Which concept the icon represents and when to use it, including what it explicitly does **not** stand for (e.g. person vs. object, direction vs. place). Stated directly, without `"This pictogram is used to"`-style openings. |
| `synonyms` | string[] | model | Fitting words/synonyms in the record's language. |

The three content fields are written in the language of the containing directory
(`<lang>/`); the JSON keys stay English so consumers are language-independent.
No file name is referenced anywhere. The model never sees the id or a file name.
Consumers key on `id`.

| Aspect | Value |
| --- | --- |
| Endpoint | OpenAI-compatible chat completions at `{base_url}/chat/completions` |
| Default base URL | `https://openrouter.ai/api/v1` |
| Default model | `deepseek/deepseek-v4-flash-vision-exp` |
| Key | `--api-key`, else `OPENROUTER_API_KEY` |
| Headers | `User-Agent` (Cloudflare rejects Python's default), plus OpenRouter `HTTP-Referer` / `X-Title` |
| Image | sent as a **base64 data URL** |
| Structured output | `response_format` `json_schema` (`--no-json-schema` for models without strict schema support) |
| Output | `<out-dir>/<lang>/[id]_description.json` |
| Default `--out-dir` | `<icons-dir>/descriptions` |
| Languages | `--lang en de` (default `en`); `--limit` counts icons |
| Cache | an existing **non-empty** file is a cache hit (stop/resume-safe) |
| `--force` | regenerate even when the file exists |
| Writes | **atomic** (temp file + `os.replace`, like `fetch.py`) |

Flags: `--icons-dir --out-dir --lang --model --base-url --api-key --workers
--limit --timeout --retries --force --dry-run --no-json-schema`.

Exit codes: **0** success, **1** one or more failures, **2** no API key,
**130** interrupted (`SIGINT`).

Examples:

```bash
# Plan only: list what would be generated
uv run python scripts/generate_icon_descriptions.py --dry-run

# Generate English (default) into icons/descriptions/en/, 8 parallel requests
OPENROUTER_API_KEY=… uv run python scripts/generate_icon_descriptions.py --workers 8

# Generate English + German into icons/descriptions/{en,de}/
OPENROUTER_API_KEY=… uv run python scripts/generate_icon_descriptions.py \
  --lang en de --workers 8

# Regenerate a small subset with a different model
uv run python scripts/generate_icon_descriptions.py \
  --model deepseek/deepseek-v4-flash-vision-exp --limit 50 --force
```

## 4. Invariants

Inherited verbatim from [`icon-descriptions.md`](icon-descriptions.md) §5,
[`multilingual.md`](multilingual.md) §6 and [`AGENTS.md`](../AGENTS.md):

- The model sees **only words** — no ids or filenames
  (`test_labels_never_expose_ids_or_filenames`).
- Every shown label resolves back to the same pictogram
  (`test_search_labels_round_trip`).
- Search stays **AND** over all query tokens; descriptions only add candidates
  and ranking, never loosen the AND filter.
- `catalog.py` stays **Pillow-free** and **network-free**; descriptions are read
  from disk and any query embedding is supplied by the caller.
- A metadata-only index still resolves
  (`test_metadata_only_catalog_resolves_to_fetchable_id`).
- The public API (`Catalog.search/resolve/ensure`, MCP tools) stays backward
  compatible.
- Retrieval is **deterministic**: equal scores tie-break on the natural file
  key; absent descriptions/index reproduce today’s ordering exactly.

## 5. Acceptance / measurement and open questions

**Acceptance**

- Phase 2/3: with descriptions absent, catalog behaviour is byte-identical to
  today (parity test).
- Phase 3: on the Phase 5 evaluation set, top-1 accuracy and MRR improve over
  the lexical baseline while wrong-hit rate does not rise; thresholds are
  pinned in CI.
- Phase 4: without the embedding artifact the Phase 3 ordering is reproduced.
- Generated descriptions are spot-checked against the §1 trap words before they
  are trusted for ranking.

**Open questions**

- Are generated descriptions **tracked in git**, or treated like the PNGs
  (gitignored, regenerated)? They are text and far smaller than the ~338 MB PNG
  set, but there are ~13,800 of them.
- Where does the FTS index live — rebuilt in memory per process, or a cached
  `descriptions.sqlite` artifact, and how is staleness detected?
- `_tokenize` (`[^\W_]+`) and FTS5’s `unicode61` may segment compounds
  differently; which one is authoritative, and how is the query built to avoid
  divergence?
- How much BM25 weight is right, and is a single `w` enough across query types?
- How does the per-request language of [`multilingual.md`](multilingual.md) map
  onto the generated `<lang>/` description directories (e.g. fall back to `de`)?
- Should any description text (synonyms, trap notes) be surface-able as
  word-only detail lines, or kept purely for ranking?
- Is Phase 4 (semantics) worth shipping, given it needs an external/local
  embedding endpoint and a caller-supplied query vector?
