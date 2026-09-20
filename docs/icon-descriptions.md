# Better icon descriptions

*Making the word layer [`arasaac_mcp/catalog.py`](../arasaac_mcp/catalog.py) work
with unambiguous, verified words.*

## 1. Goal and problem

The model addresses pictograms **only by words** (see
[`scripts/prompt.md`](../scripts/prompt.md) §3 and [`AGENTS.md`](../AGENTS.md),
“The agent tool contract is WORD-BASED”). `catalog.py` maps those words to files.
The quality of the result therefore depends almost entirely on this word layer.
Today it is a thin wrapper over the ARASAAC keywords: terse, sometimes
misleading and unverified.

Known cases from [`scripts/prompt.md`](../scripts/prompt.md) §7:

- `27206_verbleiben.png` does **not** show “stay/remain”.
- `7044_vor.png` / `13028_vor.png` are not a usable spatial “in front of”.
- `13368_stehen.png` does not fit a *standing car*.
- Several pictograms share one word (`Auto` → `Auto (KFZ)`, `Auto (Wagen)`), and
  `Schüler` stays ambiguous even though the word is shared.

**Goal:** verified, unambiguous descriptions with synonyms, word stems and
gender/number variants, so that `search`/`resolve` find the right candidate —
without breaking the existing invariants of the word layer.

## 2. Current state in code

### 2.1 Index and data model

- `icons/metadata_de.json` (~13,800 entries) is the source; `_load_index` reads
  `_id`, `keywords[].keyword`, `tags` and `categories` from it.
- `Pictogram` (`@dataclass(frozen=True)`) carries only
  `file`, `desc`, `keywords`, `extra`, `pic_id`.
- The filename is `[id]_[description].png`. Without a local PNG,
  `_synthesize_file` (via `_slug`) produces exactly the name
  `scripts/download_icons.py` would write.
- `desc` comes from the filename (`desc_by_id`) or falls back to
  `_first_keyword`; `word_of` prefers the first keyword, else `desc`.

### 2.2 Agent-facing words and labels

- `Catalog.label_of` appends a unique synonym in parentheses when a word is
  ambiguous: `Auto (KFZ)`. It is driven by `_keyword_counts`.
- When there is no unique synonym the label stays shared (`Schüler`) — pinned by
  `tests/test_catalog.py::test_label_of_shared_word_without_unique_synonym_stays_shared`.

### 2.3 Search and resolution

- `_tokenize` (regex `[^\W_]+`, lower-cased) and `_score`: **AND** over all
  tokens; keyword exact 6, prefix 4, substring 2, `desc` 3, `extra` 1, a small
  penalty per keyword. Stemming is only this naive prefix/substring behaviour
  (`rotes` → `rot`, see `test_search_forgives_plural_stem`).
- `search` → `_dedupe_by_label` → `search_lines` (word-only lines).
- `resolve` recognises `base (qualifier)`, prefers the *plain* label
  (`Auto` → `Auto`, not `Auto (KFZ)`) and otherwise falls back to `_score`
  (`test_resolve_prefers_the_candidate_with_the_plain_label`).
- `ensure`/`path_of` resolve a word to a local file and fetch missing PNGs via
  `arasaac_mcp/fetch.py`; `catalog.py` itself stays network-free.

### 2.4 Surface and tests

- MCP: `search_pictograms` (`arasaac_mcp/mcp/search_pictograms.py`) and
  `view_pictogram` (`arasaac_mcp/mcp/view_pictogram.py`).
- Tests: `tests/test_catalog.py` enforces, among other things, the **label
  round-trip** (`test_search_labels_round_trip`) and that **no IDs or filenames**
  reach the model (`test_labels_never_expose_ids_or_filenames`).

### 2.5 Unused metadata

`metadata_de.json` provides far more per entry than the index uses today:

```json
{
  "_id": 2239,
  "keywords": [{"type": 2, "keyword": "Biene", "hasLocution": true, "plural": "Bienen"}],
  "synsets": ["02209508-n"],
  "categories": ["herbivorous", "insect", "..."],
  "tags": ["animal", "herbivorous", "..."],
  "sex": false, "schematic": false, "violence": false,
  "aac": false, "aacColor": false, "skin": false, "hair": false,
  "downloads": 0
}
```

Currently ignored: `keywords[].plural`, `keywords[].type`,
`keywords[].hasLocution`, `synsets`, `sex`, `schematic`, `violence`, `aac`,
`aacColor`, `skin`, `hair`, `downloads`.

## 3. Observed gaps

1. **Metadata left on the table** — plural, keyword type (`type`), `synsets` and
   the image flags (`schematic`, `violence`, `sex`, `aac`) reach neither
   `Pictogram` nor `_score`.
2. **`desc`/`word_of` are not curated** — the primary description is the filename
   slug or the first keyword; either can differ from the intended word.
3. **The qualifier is a label heuristic** — `label_of` repairs ambiguity after
   the fact by appending a synonym and fails when there is none (`Schüler`).
4. **Stemming is ad hoc** — no lemma, no German compounds (`Händewaschen`,
   `Schulranzen`), only prefix/substring matching in `_score`.
5. **Purely lexical** — no semantic similarity; `synsets`/`tags` are not used as
   a bridge between synonyms.
6. **Traps live only in the prompt** — `verbleiben`, `vor`, `stehen` are
   documented in [`scripts/prompt.md`](../scripts/prompt.md) §7, but the catalog
   does not know them and cannot warn.
7. **Single language** — everything hangs off `metadata_de.json`, although
   `download_icons.py` already knows `--lang`.

## 4. Plan

### Phase 1 — Richer metadata in the index

Extend `Pictogram` with optional fields (`plural`, `keyword_types`, `synsets`,
`flags`) and have `_load_index` fill them. The dataclass stays frozen with
defaults so existing constructor calls and tests keep working.

- Files: `arasaac_mcp/catalog.py`.
- Tests: `tests/test_catalog.py` — the index of an entry with `plural`/`type`/
  `synsets`/`violence`.

### Phase 2 — Curated descriptions

A verified override table (e.g. `icons/descriptions_de.json` or
`arasaac_mcp/words/descriptions_de.json`) with `pic_id` → preferred word,
synonyms, an optional qualifier, a role and a note. `word_of`/`label_of` consult
it first; the ARASAAC index stays the fallback.

- Files: `arasaac_mcp/catalog.py`, the new override file, possibly
  `scripts/build_descriptions.py` to generate/populate it.
- Tests: round-trip over the overrides; the `Schüler` case becomes unambiguous;
  the existing `label_of` tests stay valid.

### Phase 3 — Better word forms

German stemming/lemmatisation plus simple compound splitting as preprocessing of
query and index; the AND semantics and the determinism of `resolve` are
preserved.

- Files: `arasaac_mcp/catalog.py` (tokenisation/`_score`).
- Tests: `test_search_forgives_plural_stem` stays; new cases for
  `Schülerinnen`, `Händewaschen`.

### Phase 4 — Light semantics

An optional embedding vector per pictogram, computed **offline** and stored next
to the index; used as a secondary ranking behind `_score`, with a lexical
fallback when the file is absent.

- Files: `arasaac_mcp/catalog.py`, a new cache artefact, an optional loader.
- Tests: ranking is identical without embeddings (fallback path).

### Phase 5 — Mark traps

Curated `trap`/`note` fields and a warning in `search_lines` and
`view_pictogram` for words such as `verbleiben` and `vor`.

- Files: `arasaac_mcp/catalog.py`, `arasaac_mcp/mcp/search_pictograms.py`,
  `arasaac_mcp/mcp/view_pictogram.py`.
- Tests: known traps are flagged in the output.

### Phase 6 — Multilingual

The full plan now lives in [`multilingual.md`](multilingual.md) (decisions,
phases, per-language invariants). Phases 1–5 of this document stay
prerequisites: richer metadata fields (1), per-language curated descriptions
(2), per-language stemming (3) and per-language trap marks (5). This phase
covers only the catalog part: `metadata_<lang>.json` instead of the fixed
`metadata_de.json`, with a per-request `lang` parameter.

- Files: `arasaac_mcp/catalog.py`, `arasaac_mcp/mcp/context.py`,
  `scripts/download_icons.py`.
- Tests: index building with `metadata_en.json` as an example.

## 5. Invariants

- The model sees **only words** — no IDs or filenames
  (`test_labels_never_expose_ids_or_filenames`).
- Every shown label resolves back to the same pictogram
  (`test_search_labels_round_trip`); this also holds for overrides.
- Search stays **AND** over all query tokens.
- `catalog.py` stays **Pillow-free**; network access happens only via
  `ensure`/`fetch.py`.
- A metadata-only index must still resolve
  (`test_metadata_only_catalog_resolves_to_fetchable_id`).
- The public API (`Catalog.search/resolve/ensure`, MCP tools) stays backward
  compatible.

## 6. Acceptance / measurement

- A small evaluation set of German sentences is played through repeatedly;
  the measured value is the rate of wrong or ambiguous word hits.
- New words and synonyms are pinned as round-trip tests before they move into the
  overrides.
- Known traps are marked in the catalog, not only in the prompt.
