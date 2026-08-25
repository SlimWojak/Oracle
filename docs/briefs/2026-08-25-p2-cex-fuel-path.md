# P2 — CEX fuel measurement path (authorized)

CTO 2026-08-25. Frozen from P1 v5 / D-030. **Implement this brief only.**
P3 scoring is unauthorized. No M2. No 1h. No `[2, 4%)` in primary outputs.

## Goal

Land feature code, as-of rules, and hooks for the EXP-002 P3 gate so a
later P3 commission can compute F without reinventing the measurement.

## Implement

1. **Metrics loader** for Binance Vision UM 5-minute `BTCUSDT` metrics.
   Fields: `create_time`, `sum_open_interest`, `sum_open_interest_value`,
   `sum_toptrader_long_short_ratio`. DATA_CONTRACT as-of / realignment.
2. **Cohort state machine** (`cex_oi_cohort_v0`) exactly as P1 v5:
   unallocated opening bucket; quantity Δ from Q and LSR; pro-rata
   reductions; conservation check; burn-in through 2025-05-24.
3. **Decision join:** last metrics row with interval end ≤ T (D-017).
   Value surviving priced quantities at P_T (consolidated index).
   Adverse-entry distance; bands `(0, 1%)` and `[1, 2%)` only.
4. **Cluster-row table** from EXP-000 **4h** `index_clusters.json`:
   pure-direction only; earliest far-edge-eligible T per
   (cluster, direction, band); skip ineligible. Attach fuel, OI-only
   USD, trailing-path baseline at that T.
5. **Target hook (not scored):** for each cluster-row, query HL fills
   Parquet for book-hitting vs backstop USD on `(T, T+4h]`, same side,
   fill-distance in the same band vs P_T. Dedup by `tid`. Do **not**
   compute Spearman / F / floor / verdicts.
6. **Tests:** tiny synthetic fixtures for the state machine
   (conservation, unallocated never bands, LSR-only Δ, clip-at-zero),
   as-of join, adverse-entry, far-edge eligibility, cluster-row
   reduction. No full-tape golden.

## Outputs

- Library code under `src/oracle_research/` (names at your discretion;
  public functions, no new deps).
- Optional dexter-derived table under
  `{data_root}/derived/cex_oi_cohort_v0/` with a D-019 manifest, **only
  if** a small smoke on construct-dev is needed to prove the hook.
  Default: code + unit tests, no full-window materialization in this PR.
- Short `reports/p2_cex_fuel_path.md` describing how to run the hook.
  No ledger/decision/thesis edits.

## Fences

- Do not edit `THESIS.md`, `RESEARCH_CONTRACT.md`, `DATA_CONTRACT.md`,
  `docs/DECISIONS.md`, `EXPERIMENT_LEDGER.md`, or write verdicts.
- Do not run P3. Do not print F. Do not compact Parquet. Do not add
  query infrastructure. Do not implement EXP-003.
- PR against main. Do not merge.

## Done when

`python -m unittest discover` green (including new tests), ruff clean,
PR up, report SHA + test count in Oracle Lab.
