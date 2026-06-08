# Review: `2026-05-13-visual-mapping-agent-design.md`

Reviewed file: [docs/superpowers/specs/2026-05-13-visual-mapping-agent-design.md](/C:/vibe_coding/tabToPbi/docs/superpowers/specs/2026-05-13-visual-mapping-agent-design.md)

## Findings

### 1. High: the proposed `visual_mapper.map_visual()` boundary is too wide and does not match the current pipeline

The spec moves visual type, query roles, and objects into `visual_mapper.map_visual()` ([spec lines 303-360](/C:/vibe_coding/tabToPbi/docs/superpowers/specs/2026-05-13-visual-mapping-agent-design.md:303)). In the current code, those concerns are split:

- `transformer.py` resolves Tableau semantics into normalized sheet data such as `mark_type`, `row_fields`, `col_fields`, `color_fields`, `crosstab_measures`, `show_data_labels`, `sorts`, and `visual_format` ([transformer.py](/C:/vibe_coding/tabToPbi/tab_to_pbi/transformer.py:394)).
- `generator.py` converts that normalized shape into PBIR `visualType`, `queryState`, `sortDefinition`, `objects`, and `visualContainerObjects` ([generator.py](/C:/vibe_coding/tabToPbi/tab_to_pbi/generator.py:1106)).

The design does not define which layer remains responsible for:

- `Bar` to `Column` orientation normalization
- `Automatic` mark inference
- pivot special handling (`Rows`/`Columns`/`Values`)
- title generation
- visual formatting objects
- sort definition generation

Without a narrower contract, this will duplicate logic across `transformer.py`, `generator.py`, and `visual_mapper.py`, and it is likely to regress working visuals.

Recommendation: keep `transformer.py` as the Tableau-normalization layer and keep `generator.py` as the PBIR emitter. Introduce the registry first for only:

- mark type to visual type resolution
- per-visual role metadata
- additive object snippets

Do not make `visual_mapper.py` own full visual assembly in the first iteration.

### 2. High: runtime auto-persist of inferred mappings will make migrations nondeterministic

The spec proposes that runtime Claude results with score `>= 0.8` are emitted and auto-persisted into `samples/visual_mappings.json` ([spec lines 52-60](/C:/vibe_coding/tabToPbi/docs/superpowers/specs/2026-05-13-visual-mapping-agent-design.md:52), [321-325](/C:/vibe_coding/tabToPbi/docs/superpowers/specs/2026-05-13-visual-mapping-agent-design.md:321)). That creates several problems:

- identical migrations can produce different repo state over time
- CI and local runs will diverge based on whether LLM access was available
- the working tree becomes dirty as a side effect of a normal conversion run
- concurrent runs can race on the registry file

Recommendation: runtime fallback should never mutate the canonical registry. Persist inferred candidates to a separate artifact such as:

- `output/<stem>.visual_mapping_suggestions.json`, or
- a review queue consumed by `visual_agent.py`

Only the offline builder should update `samples/visual_mappings.json`.

### 3. High: pairing transformed sheets to generated `visual.json` files by sheet name is brittle

The offline builder relies on matching `output/<stem>.transformed.json` to generated `visual.json` files by sheet name ([spec lines 266-279](/C:/vibe_coding/tabToPbi/docs/superpowers/specs/2026-05-13-visual-mapping-agent-design.md:266)). The current generator can emit multiple visuals for one sheet when multiple measures are present, naming them as `"<sheet> - <measure>"` while keeping the page name as the original sheet ([transformer.py lines 510-530](/C:/vibe_coding/tabToPbi/tab_to_pbi/transformer.py:510), [generator.py lines 946-963](/C:/vibe_coding/tabToPbi/tab_to_pbi/generator.py:946)).

That means sheet-name matching is not a stable provenance key.

Recommendation: add explicit provenance fields during generation, for example:

- `source_sheet_name`
- `source_workbook_name`
- `source_visual_index`
- optional stable hash of the normalized field layout

Then let `visual_agent.py` match on provenance, not display name.

### 4. Medium: the confidence model is internally inconsistent

The spec defines tiered confidence values as `validated`, `generated`, and `inferred` ([spec lines 84-92](/C:/vibe_coding/tabToPbi/docs/superpowers/specs/2026-05-13-visual-mapping-agent-design.md:84)). But the example schema also uses `medium` for `Circle` ([spec line 134](/C:/vibe_coding/tabToPbi/docs/superpowers/specs/2026-05-13-visual-mapping-agent-design.md:134)), while runtime fallback uses numeric thresholds (`>= 0.8`, `0.5-0.79`, `< 0.5`) ([spec lines 321-325](/C:/vibe_coding/tabToPbi/docs/superpowers/specs/2026-05-13-visual-mapping-agent-design.md:321)).

Recommendation: separate provenance from score:

- `status`: `validated | generated | inferred`
- `score`: optional float for LLM-only outputs

Do not mix review state and model confidence into one field.

### 5. Medium: the spec underestimates how much of current behavior is encoded outside `MARK_TO_VISUAL`

The problem statement centers on `MARK_TO_VISUAL` and `_VISUAL_ROLES` ([spec lines 13-16](/C:/vibe_coding/tabToPbi/docs/superpowers/specs/2026-05-13-visual-mapping-agent-design.md:13)), but the current behavior also depends on:

- `_infer_mark_type()` for `Automatic` ([transformer.py](/C:/vibe_coding/tabToPbi/tab_to_pbi/transformer.py:697))
- row/column measure checks that flip `Bar` to `Column` ([transformer.py lines 428-451](/C:/vibe_coding/tabToPbi/tab_to_pbi/transformer.py:428))
- pivot projection helpers and object rules ([generator.py lines 1042-1194](/C:/vibe_coding/tabToPbi/tab_to_pbi/generator.py:1042))
- visual formatting object builders ([generator.py lines 1179-1241](/C:/vibe_coding/tabToPbi/tab_to_pbi/generator.py:1179))

Recommendation: explicitly classify mappings into three layers:

- semantic normalization rules
- PBIR role/projection templates
- PBIR object fragments

Only the last two belong in the registry. Semantic normalization should stay in code unless there is a very strong reason to data-drive it.

### 6. Medium: the offline "diff against empty baseline" extraction rule is underspecified

The builder extracts object fragments by diffing against an empty baseline ([spec line 278](/C:/vibe_coding/tabToPbi/docs/superpowers/specs/2026-05-13-visual-mapping-agent-design.md:278)). That is not enough to distinguish:

- required default objects emitted by Power BI
- cosmetic noise written by Desktop
- true Tableau-driven behavior

Recommendation: compare against a curated per-visual baseline generated from a minimal known report, not an empty object. Otherwise the registry will accumulate incidental PBIR output rather than meaningful mappings.

## Recommended Direction

### Phase 1

Build only the offline registry builder and doc generator.

- Generate `samples/visual_mappings.json`
- Regenerate `docs/visual_conversion.md`
- Keep runtime behavior deterministic
- Use the registry only for `mark_type_mapping` and explicit visual object snippets already validated from samples

### Phase 2

Introduce registry-backed role metadata in `generator.py`.

- Replace `_VISUAL_ROLES` reads with registry lookups
- Keep existing code paths as fallback
- Add provenance metadata so `visual_agent.py` can round-trip reliably

### Phase 3

Add optional runtime suggestion mode, not runtime mutation.

- LLM output goes to a suggestion artifact in `output/`
- migration report references those suggestions
- human validation plus offline rebuild promotes them into the canonical registry

## Concrete Recommendation

If the goal is to reduce manual maintenance without destabilizing the converter, the safest design is:

1. Make `visual_agent.py` the only writer of `samples/visual_mappings.json`.
2. Keep `transformer.py` responsible for Tableau interpretation.
3. Keep `generator.py` responsible for PBIR emission.
4. Treat runtime LLM output as advisory, never canonical.
5. Add stable provenance keys before attempting any automated extraction from generated PBIR.

That sequence solves the documentation drift problem immediately and avoids turning normal migration runs into stateful training events.
