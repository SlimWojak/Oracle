# P3 Phase B addendum — streaming as-of (authorized)

CTO 2026-08-25. Mechanical only. **Not a construct change.**
Same `cex_oi_cohort_v0` math, same as-of rule, same four cells.
No F change. No P4. No 2026 look. No ledger.

## Cause (banked)

Phase B OOM on dexter: `run_cex_oi_cohort_v0` retains a frozen
`CohortSnapshot` (full priced-cohort tuples) at every 5-minute row
(~496k rows). That is O(n²) copies. earlyoom SIGTERM at ~116 GiB RSS
during `loading Binance UM metrics`, before cluster rows / attach.
`harness_status` none. No `reports/exp002`.

## Implement

1. **Streaming as-of walk.** New public entry (name at your discretion)
   that shares the existing state machine and:
   - keeps only the current live `long_side` / `short_side`
   - emits a snapshot only when a metrics `interval_end` is the as-of
     row for at least one requested T (last `interval_end` ≤ T)
   - may stop after the last requested T
   Existing `run_cex_oi_cohort_v0` may stay for tiny fixtures. The
   Phase B runner must **not** call the retain-all path on the full tape.

2. **Split eligibility from fuel.** Far-edge T selection uses bars +
   4h clusters only. Collect those decision timestamps first (window
   `cluster.start ∈ [2025-05-25, 2026-01-01)`), then run the as-of walk
   on that T set, then `decision_fuel` / cluster rows.

3. **Keep-last unique `interval_end`.** Land the day-boundary overlap
   hygiene in the metrics loader: when two daily zips share an
   `interval_end`, keep the later file's row. Document the two known
   overlaps (2024-04-07/08 and 2024-04-30/05-01) in the loader
   docstring or a short comment. This is already authorized for the
   failed run.

4. **Runner.** Use the streaming path. Attach HL targets only for those
   windowed rows. Still no Parquet compact, no query infra, no 2026
   score.

5. **Tests.** Tiny fixtures only:
   - as-of walk at chosen T's equals `asof_snapshot(full_walk, T)`
   - keep-last unique on two overlapping `interval_end` rows
   - existing conservation / unallocated / LSR-only tests stay green

## Outputs

PR against main. Do not merge. Do not rerun the tape until CTO merges.
Do not include `reports/exp002/` in this PR.

## Fences

- Do not change cohort accounting, bands, F, bootstrap, or windows.
- Do not spill a full-tape snapshot store unless the as-of walk still
  OOMs (then stop and report; do not invent a derived tape).
- Do not edit `THESIS.md`, contracts, `DECISIONS.md`, or the ledger.

## Done when

`python -m unittest discover` green, ruff clean, PR up, SHA + test
count in Oracle Lab.
