# P3 — Execute EXP-002 fuel construct gate (authorized)

CTO 2026-08-25. Frozen from P1 v5 / D-030. **Implement this brief only.**
P4 / EXP-003 unauthorized. No 2026 look. No 1h. No `[2, 4%)` in `F`.
No ledger / decision / thesis verdicts.

## Goal

Score the four primary cells with the P2 measurement path already on main.
Emit a construct-gate report. CTO banks PASS / FAIL / NULL after the run.

Reuse `oracle_research.cex_fuel` as-is. Do not reopen cohort mechanics.

## Two phases (one commission)

**Phase A (now):** scoring library + tests + run script. PR against main.
Do not merge. Do not run the full tape.

**Phase B (after CTO merge):** dexter run of construct-dev + construct-val.
Open a follow-up PR with `reports/exp002/*` only.

## Primary family (frozen)

Exactly:

`4h × {up, down} × {(0, 1%), [1, 2%)}`

Window assignment uses `cluster.start_timestamp` (UTC), half-open:

| Window | Interval |
|---|---|
| construct-dev | `[2025-05-25, 2025-09-01)` |
| construct-val | `[2025-09-01, 2026-01-01)` |
| stability Sep–Oct | `[2025-09-01, 2025-11-01)` |
| stability Nov–Dec | `[2025-11-01, 2026-01-01)` |

Do not score `≥ 2026-01-01`. Coverage floors: dev ≥ 10 / cell, val ≥ 15 /
cell, each stability block ≥ 10 / cell. No further relaxation.

## Scoring (numpy only; no new deps)

Target is `book_hitting_usd` from the P2 HL hook. Backstop is never pooled
and never enters Spearman.

Per cell, on that window's cluster-rows:

```
rho_c      = spearman(fuel_usd, book_hitting_usd)
rho_oi     = spearman(oi_only_usd, book_hitting_usd)
rho_path   = spearman(trailing_price_path_4h, book_hitting_usd)
rho_static = spearman(static_usd, book_hitting_usd)
```

Spearman: rank both series (average ranks for ties), then Pearson on the
ranks. **Defined** only if `n ≥ 5` and both series have positive finite
variance. Otherwise the cell Spearman is undefined.

`static_usd` for a row is the two-band **lumped** control, not OI times a
constant (that would be rank-identical to OI-only):

```
total = fuel_usd[(0,1%)] + fuel_usd[[1,2%)]   # same cluster, same T
static[(0,1%)]  = 0.75 * total
static[[1,2%)]  = 0.25 * total
```

Missing sibling-band fuel counts as 0.

Family statistics (equal-weight mean over the four cells):

```
F_vs_oi   = mean(rho_c - rho_oi)
F_vs_path = mean(rho_c - rho_path)
F_static  = mean(rho_static - rho_oi)
```

Any undefined Spearman on a required cell → do not lock (dev) / integrity
fail (val or stability).

## Bootstrap and floor

One **family-wide** weekly draw. A cluster belongs to the UTC week of
`cluster.start` (Monday 00:00), already on `ClusterFuelRow.week_start_timestamp`.
A drawn week carries every selected cluster's **linked rows across both
bands**. No independent cell resampling.

```
rng = numpy.random.default_rng(20250825)
B = 1000
draw weeks with replacement
F* = F_vs_oi on the four cell-rows belonging to the drawn clusters
SE = sample_std(F*, ddof=1)
floor = max(0.10, 2 * SE)   # six decimals; lock on construct-dev only
CI95 = (percentile 2.5, percentile 97.5) of F*
```

Lock the floor on construct-dev. Apply that locked floor to construct-val.
If any primary cell is below its dev floor or any required Spearman is
undefined on construct-dev: **do not lock**; harness status is NULL.

CI95 "excludes 0" means `0` is strictly outside `[p2.5, p97.5]`.
PASS requires the construct-val CI95 of `F_vs_oi` and of `F_vs_path`
to exclude 0 (lower bound > 0 in practice).

## Shape (construct-val only)

On each val cell, stable-sort rows by
`(fuel_usd, cluster_index, decision_timestamp)`. Rank `0 .. n-1`.

```
tercile = min(2, floor(3 * rank / n))
m_k = mean(book_hitting_usd) in tercile k
```

Integrity NULL if any tercile has < 5 rows.

Hard flip: `m3 < 0.8 * m1` when `m1 > 0`, else `m3 < m1`.

Shape pass: `m3 ≥ m1` in **≥ 3 of 4** cells, and **zero** hard flips.

## Stability (construct-val blocks)

Sep–Oct and Nov–Dec are scored independently with the same four-cell `F_vs_oi`.
Each block must have ≥ 10 eligible clusters per primary cell, a defined
`F_vs_oi`, and `F_vs_oi > 0`. A block that fails integrity is a **failed
block**, not dropped.

## Mechanical harness status (not a ledger verdict)

Emit `harness_status` from these clauses only:

**NULL** if any of: a primary cell below its window floor after
feature/target construction; any required Spearman undefined; floor not
locked; conservation / LSR / tape-coverage fail surfaced by the P2 path.

**PASS** (construct-val, all of): every cell ≥ 15; Spearmans defined;
`F_vs_oi ≥ floor` and val CI95 excludes 0; same for `F_vs_path`;
shape gate; both stability blocks pass; `F_static` does not exceed
`F_vs_oi`.

**FAIL** if integrity holds and a PASS clause fails.

Do not edit `EXPERIMENT_LEDGER.md`. CTO banks the verdict.

## Phase A implement

1. Scoring functions under `src/oracle_research/` (names at your discretion;
   public; numpy only).
2. `scripts/run_p3_construct_gate.py`:
   - `--data-root` (dexter: `/home/a8ra_dgx/oracle-data`)
   - `--clusters` default `reports/exp000/index_clusters.json`
   - rebuild the D-022 median index the same way as
     `scripts/run_p1_eligibility_census.py` (`load_index`)
   - `load_metrics_dir` → `run_cex_oi_cohort_v0` → `build_cluster_fuel_rows`
   - attach `hl_target_for_cluster_row` (stream Parquet per `source_path`;
     do not compact; do not globally sort)
   - score construct-dev (lock floor) then construct-val + both stability
     blocks
   - write `reports/exp002/construct_gate.json`, `.md`, and a D-019
     `construct_gate.provenance.json`
3. Tests on tiny synthetic fixtures: defined/undefined Spearman, lumped
   static ≠ rank(OI), family-wide week linkage (drawing a week moves both
   bands), seeded bootstrap reproducibility, floor recipe, tercile edges
   at n=15, hard-flip, stability fail-is-fail. No full-tape golden.

## Phase B run (after merge only)

On dexter, from the merged SHA:

```
python scripts/run_p3_construct_gate.py --data-root /home/a8ra_dgx/oracle-data
```

PR the three `reports/exp002/` files. No other edits.

## Fences

- Do not edit `THESIS.md`, `RESEARCH_CONTRACT.md`, `DATA_CONTRACT.md`,
  `docs/DECISIONS.md`, `EXPERIMENT_LEDGER.md`, or write verdicts.
- Do not score 2026 windows. Do not put 1h or `[2, 4%)` in `F`.
- Do not implement EXP-003 / P4. Do not compact Parquet. Do not add
  query infrastructure. No new dependencies.
- Phase A PR against main. Do not merge.

## Done when

Phase A: `python -m unittest discover` green, ruff clean, PR up, SHA +
test count in Oracle Lab.

Phase B: after merge, dexter run finished, report PR up, harness_status
quoted. Still no ledger edit.
