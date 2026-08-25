# CTO seat handover

Agent-to-agent orientation. Update this file before every seat rotation.
Read order for an incoming seat: `AGENTS.md` -> this file -> `EXPERIMENT_LEDGER.md`
-> `docs/DECISIONS.md`.

Operational access details (hosts, accounts, profiles, local paths, session
identifiers) live in `docs/HANDOVER_LOCAL.md` on the canonical workstation.
That file is gitignored and must never be committed; this repository is public.

## State as of 2026-08-25 (Grok Bot CTO; P3 Phase B rerun authorized)

### Topology (abstract; specifics in the local file)

- Canonical repository seat: user workstation.
- Data host: remote headless DGX (see `AGENTS.md` topology section). Owns the
  immutable raw-data root; has a repo clone, venv, tmux, uv, aws-cli, lz4.
- Requester-pays S3 access to the Hyperliquid archive works after an org-level
  SCP edit (details local).

### Data on hand (data host raw root)

- Binance Vision: spot+UM perp 1m klines and funding 2020-01..2026-07, UM
  daily metrics 2021-12..2026-08. 1,962 files, checksum-verified, manifested.
  99.97% bar coverage.
- Hyperliquid asset_ctxs: per-minute contexts (incl. quoted impact prices, OI,
  premium) 2023-05-20..present, ~9GB.
- Hyperliquid node_fills: full fill history 2025-05-25..2026-08-23, two
  formats (old hourly format to 2025-07-27, 1,507 files ~30GB; then by-block
  hourly, 9,405 files ~240GB). Pull complete and verified against S3 by
  dry-run re-sync (zero missing objects). Trailing hours can be topped up
  with the same sync if ever needed.
- Hyperliquid samples: two schema-inspection fill hours (one per format, incl.
  2025-10-10 hour 21, the record cascade).
- Hyperliquid l2Book BTC slice: 28,304 hourly files ~22GB, 2023-04-15..
  2026-08-01 (archive trailing edge), verified by dry-run re-sync.
- Kraken XBTUSD: official OHLCVT 1m CSVs (master to 2025-12-31 + Q1 2026;
  browser-downloaded by user due to Drive quota, sha256-verified) plus raw
  Trades pages 2026-01-01..2026-08-01 (incl. 2 patch pages recovering a
  censored API window on 2026-02-20). Trades-derived bars exact-match
  official Q1 (129,509/129,509 rows); Apr-Jul derived bars built.
- Coinbase BTC-USD 1m candles 2019-12-01..2026-07-31: 3,504,259 bars,
  11,688 verbatim response files ~198MB, zero duplicates, manifested with
  per-file sha256s.
- Derived (data host): Kraken trades-derived 1m bars for 2026-01..03
  (exact-match validated vs official) and 2026-04..07 (index input).

### Verified schema facts (load-bearing)

- Fill records carry `liquidation: {liquidatedUser, markPx, method}` with
  method in {market, backstop}; ADL appears as dir "Auto-Deleveraging".
  Dedupe liquidation totals by the liquidatedUser leg (object rides both legs).
- New fill format wraps events in blocks with `local_time` (receive) and
  `block_time` (source) - keep both per DATA_CONTRACT.
- Binance klines stamp interval START; Binance metrics dumps stamp interval
  END (-5 min realignment required, see DATA_CONTRACT). Kline open_time is ms
  before 2025-01, us after (loader handles it).
- Canonical decision timestamp is interval END (D-017); the catalogue was
  rebuilt after an advisor caught the interval-start stamping defect.

### EXP-000: CLOSED, PASS (2026-08-24)

Full trail in the ledger. Load-bearing outcomes:
- Labels now come from the D-022 median-of-three consolidated index
  (Binance/Kraken/Coinbase, >=2-of-3 rule, wall-clock horizons). The index
  grid is MORE complete than any member (108 missing minutes 2020-01..
  2026-07). Canonical inventory: `reports/exp000/index_clusters.json`
  (1,658 / 1,935 clusters at 1h / 4h).
- The Kraken gate (D-013/D-021) triggered escalation at 5.90%/4.26%
  disagreement; disputes were marginal barrier events; consolidation fixed
  them by construction (sensitivity: 0 direction flips, ~3% churn).
- Splits frozen as D-023: dev 2020-2023, val 2024, test 2025..2026-07 as
  two contiguous OOS periods; straddle-drop boundary rule; per-challenger
  ladders share the final test.
- Debt: challenger_history.* still derives from the Binance-only
  clusters.json; regenerate from index_clusters.json before ladder work.

### EXP-001: CLOSED, FAIL (2026-08-24)

Phase 1 tractable share 39.06%; Phase 2 combined reconstruction accuracy 8.02%
(663 isolated events evaluable on Oct cascade; cross-margin unobserved without
wallet state). D-018 demotion: HL challenger is realized-mass diagnostics only.
Artifacts: `reports/exp001/stratification_census.*`, `reports/exp001/reconstruction_*`.

### D-012 derived HL fills store

P0 BANKED (main `656c4fb`). Canonical analytical source:
`{data_root}/derived/hyperliquid/fills/v1/all_fills`, Hive-partitioned by UTC
`date=YYYY-MM-DD/hour=HH` with `zstd` Parquet by default. Install opt-in deps
with `python -m pip install -e '.[dev,hyperliquid,analytics]'`.

Run on the data host:

```bash
python scripts/build_hl_btc_liquidations.py \
  --data-root /home/a8ra_dgx/oracle-data \
  --overwrite

python scripts/run_hl_parquet_census_parity.py \
  --data-root /home/a8ra_dgx/oracle-data
```

The builder writes `manifest.json` and `manifest.provenance.json` beside the
derived table under the data root. The parity gate reads Parquet via DuckDB
only, streams per `source_path` to avoid a global-sort OOM, replays the EXP-001 Phase 1 census state machine, and emits
`reports/infra_hl_parquet_v1/parity.{json,md}` plus a D-019 sidecar. In cloud
or CI without the data host, the parity script writes a `MISSING_DATA` report
and exits non-zero; do not invent passing parity numbers.

### Next work (in order)

Authoritative sequence remains `docs/glide_path.md`. Current beat is **P3 Phase B**.

1. P2 banked on main `ed508e7` (PR #4).
2. P3 Phase A banked on main `889ea56` (PR #5): scoring lib + runner, 191 tests.
3. Streaming as-of banked on main `69a2e89` (PR #6). Engineer: Phase B
   rerun on dexter from that SHA:
   `python scripts/run_p3_construct_gate.py --data-root /home/a8ra_dgx/oracle-data`.
   PR only `reports/exp002/construct_gate.{json,md,provenance.json}`.
   Stop + ETA if wall looks > ~8h after first attach. No ledger.
4. Still debt, later: regenerate `challenger_history` from
   `index_clusters.json` (P5); large-cluster weight policy before M2.

### Glide path (authoritative sequence)

Active research sequence is `docs/glide_path.md` (v1). **P1 BANKED**
(four-cell `cex_oi_cohort_v0`; D-029/030/031 accepted). **P2 BANKED**
(`ed508e7`). **P3 Phase A BANKED** (`889ea56`). **Phase B authorized.** Brief:
`docs/briefs/2026-08-25-p3-fuel-construct-gate.md`. Census:
`reports/p1_eligibility_census.json`. Golden pins on main `e5b6dfd`.
No P4, no M2.


### Seat note (2026-08-24)

Grok Bot Chief of Staff is CTO seat. Oracle Engineer implements frozen specs
only. Cursor Phase 2 complete; EXP-001 banked from this rotation.

### Operating notes

- Thin orchestration per AGENTS.md: delegate mechanical work (Composer for
  plumbing, Grok high for tricky vectorization) with tight specs; lead seat
  reviews everything; contracts/ledger/decisions never delegated. Property
  tests against `labels.first_passage` are the pattern for any new labeller.
- An external advisory/red-team seat exists (read-only); its first 2026-08-23
  review produced D-016..D-019, EXP-001, and the D-017 timestamp fix; its
  second (same day) endorsed the Kraken escalation, requested the blind
  D-022 freeze, a D-021 interpretation caveat, D-019 provenance sidecars on
  committed artifacts, and doc-sync hygiene (all executed or in flight).
- Venue APIs can serve censored tape: the Kraken Trades API omitted a
  906-second cascade window that official bars contained; always validate
  trades-derived bars against an official overlap before trusting them.
- Run `python -m unittest discover` and `ruff check .` (use repo venv) before
  handing off. 191 tests (7 skipped) green at P3 Phase A bank.
- Known open decisions listed at the bottom of `docs/DECISIONS.md`. Settle
  the large-cluster weight policy before any M2 scoring; regenerate the
  challenger-history table from the index inventory before ladder design.
