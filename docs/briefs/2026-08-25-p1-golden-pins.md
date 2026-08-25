# Engineer commission — golden / byte-identity pins (hygiene only)

CTO 2026-08-25. Parallel to the P1 paper freeze. **Not a science beat.
Does not authorize P2.**

## Goal

Add tiny, unittest-guarded golden pins so deterministic primitives cannot
drift silently. Complements D-019. Same inputs → same bytes (or same
canonical JSON).

## Pin these (tiny fixtures only)

1. **Labels** — `oracle_research.labels.first_passage` on a short synthetic
   bar series (already the property-test pattern). Add a frozen expected
   JSON/tuple for one fixture.
2. **Clusters** — `cluster_positive_anchors` on a frozen tiny anchor list.
3. **Index** — `build_median_index` on three short synthetic member series
   (2-of-3 presence + median).
4. **Stratification** — `stratify_event` / `extract_btc_liquidation_events`
   on a handful of synthetic `HlFill` rows covering isolated / cross /
   market / backstop.
5. **Parquet schema** — field names + types of `hl_fills_parquet._schema()`
   (or the public schema helper). Pin the schema contract, **not** any
   Parquet file bytes.

## Hard fences

- Do **not** byte-pin complete Parquet files or anything that depends on
  PyArrow / DuckDB version.
- Do **not** compact the 82,512 dexter parts.
- Do **not** build generic query infrastructure or new derived tables.
- Do **not** refactor production code except the minimum needed to expose a
  stable schema helper if `_schema` is private (a one-line public alias is
  fine).
- Do **not** add dependencies, frameworks, or snapshot libraries.
- Do **not** edit `THESIS.md`, `RESEARCH_CONTRACT.md`, `DATA_CONTRACT.md`,
  `docs/DECISIONS.md`, `EXPERIMENT_LEDGER.md`, or write verdicts.
- Do **not** start P2 or any construct aggregate.

## Done when

- New tests live under `tests/` (e.g. `tests/test_golden_pins.py`) with
  fixtures in `tests/fixtures/golden/` if needed.
- `python -m unittest discover` is green.
- PR against main. Report in Oracle Lab. Do not merge.

## Out of scope

Science docs, EXP stubs, dexter jobs, Parquet rebuilds, query helpers.
