# Frozen Engineer spec — HL fills → Parquet + DuckDB (D-012)

**Status:** frozen for implementation (CTO, 2026-08-24)  
**Repo tip at freeze:** `dfc9261` (or later bank commits)  
**Owner:** Oracle Engineer  
**Reviewer:** CTO (Chief of Staff)  
**Out of scope:** predictive ladders, contract/ledger verdicts, `replica_cmds` spend, polishing raw LZ4 census scripts as a product.

## Goal

One-time materialize Hyperliquid `node_fills` (+ by-block) into a rebuildable columnar store so EXP-class work stops paying a full-tape LZ4/JSON scan (~75–90+ min) on every run. Aligns with D-012 (DuckDB over Parquet).

## Why now

EXP-001 closed FAIL (D-024). Fill tape is retained for **realized-mass diagnostics** and construct validation. Velocity is blocked by re-scanning ~270GB LZ4 JSON with single-threaded state machines.

## Deliverables (acceptance)

1. **Derived Parquet dataset** on the data host under the Oracle data root (not in git):
   - Path convention (propose if unset; record in manifest):  
     `{data_root}/derived/hyperliquid/fills/v1/…` partitioned sensibly (e.g. by UTC day or hour).
   - Row grain: **one normalized fill** (same semantics as `HlFill` in `src/oracle_research/hyperliquid_fills.py`).
   - Required columns (minimum):  
     `user`, `coin`, `px`, `sz`, `side`, `time_ms`, `start_position`, `dir`, `hash`, `oid`, `crossed`, `tid`, `fee`, `fee_token`,  
     `liquidation_liquidated_user`, `liquidation_mark_px`, `liquidation_method` (nullable when no liquidation object),  
     `block_time`, `local_time`, `block_number`,  
     `source_format` (`old_hourly` | `by_block`), `source_path` (relative under raw), `builder_version`.
   - Preserve both receive and source times per DATA_CONTRACT when present.
   - Do **not** drop non-BTC fills in the primary all-fills table (filter at query time). Optional second artifact: BTC-liquidation-only Parquet is allowed as a *view or derived table*, not a replacement for all-fills.

2. **DuckDB access path** (script or documented one-liner) that:
   - Registers/reads the Parquet tree read-only.
   - Reproduces EXP-001 Phase 1 census aggregates from Parquet (or from a BTC-liq derived table built from it) **without** re-reading LZ4.

3. **Parity gate (hard FAIL if missed)** vs banked  
   `reports/exp001/stratification_census.json` (commit `dfc9261`):
   - `total_btc_liquidation_events` exact match
   - `total_btc_liquidation_notional_usd` within relative `1e-9` (float) or exact if computed identically
   - `counts_by_stratum` and `notional_usd_by_stratum` exact / same tolerance
   - `counts_by_method` and `notional_usd_by_method` same
   - `tractable_share` within `1e-12` absolute  
   Emit `reports/exp002/` or `reports/infra_hl_parquet_v1/parity.{json,md}` + D-019 provenance sidecar.  
   If parity fails: do not claim done; file a short discrepancy report (no silent “close enough”).

4. **Manifest + provenance (D-019)** for the derived build:
   - repo commit SHA, builder version, input raw manifest ids / file counts, UTC start/end, output Parquet path list + content hashes (or Hive partition digest), row counts.

5. **Tests** in-repo:
   - Unit tests on a tiny fixture (checked-in synthetic fills → Parquet round-trip schema).
   - No raw HL data in git.
   - `python -m unittest discover` and `ruff check .` green.
   - Add optional deps (`pyarrow`, `duckdb`) under a new extra (e.g. `[analytics]`) — do not force them into base install.

6. **Docs:** short section in `docs/HANDOVER.md` (derived path + how to run builder + parity). No contract edits. CTO updates ledger/decisions if a new EXP id is warranted after review.

## Non-goals (explicit)

- Per-user parallel replay / checkpoints (defer until query pattern is clear).
- orjson micro-opts on the old census runners (only OK inside the one-time builder if it helps the build finish).
- GPU, live services, dashboards.
- Changing stratification rules (reuse `hl_liquidations` / census semantics from EXP-001 v3).
- Predictive features or M0–M5 ladder work.

## Implementation notes

- Reuse `oracle_research.hyperliquid_fills.iter_fills_from_lz4` / `HlFill` where possible; extend rather than fork semantics.
- Existing `scripts/build_hl_btc_liquidations.py` is a JSONL scaffold only — Parquet is the target; replace or supersede cleanly.
- Builder may stream hour-by-hour to Parquet to bound RAM; all-fills in one giant in-memory list is not acceptable on dexter.
- Prefer snappy or zstd Parquet compression; document choice in manifest.
- Idempotent rebuild: same inputs + builder_version → same row counts and parity.

## Done means

CTO can run (or Engineer demos) DuckDB census parity in **minutes**, not hours, against the banked EXP-001 numbers, with manifests committed under `reports/` and derived files only on the data host.

## Report back

Post into Oracle Lab: paths, wall time, parity table, any discrepancies, PR/commit SHA. Do not merge science conclusions — CTO banks verdicts.
