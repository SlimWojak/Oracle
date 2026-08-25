# CTO seat handover

Agent-to-agent orientation. Update this file before every seat rotation.
Read order for an incoming seat: `AGENTS.md` -> this file -> `EXPERIMENT_LEDGER.md`
-> `docs/DECISIONS.md`.

Operational access details (hosts, accounts, profiles, local paths, session
identifiers) live in `docs/HANDOVER_LOCAL.md` on the canonical workstation.
That file is gitignored and must never be committed; this repository is public.

## State as of 2026-08-25 (Codex CTO; EXP-005 NULL; STOPPED)

### Topology (abstract; specifics in the local file)

- Canonical repository seat: user workstation.
- Data host: remote headless DGX (see `AGENTS.md` topology section). Owns the
  immutable raw-data root; has a repo clone, venv, tmux, uv, aws-cli, lz4.
- Requester-pays S3 access to the Hyperliquid archive works after an org-level
  SCP edit (details local).

### Data on hand (data host raw root)

- Binance Vision: spot+UM perp 1m klines and funding 2020-01..2026-07, UM
  daily metrics 2021-12..2026-08. 1,962 files, checksum-verified, manifested.
  D-019 M1 source audit at `c430f8f`; all archives rehashed. Source-only
  four-family hourly joint coverage is 99.69% M1-dev, 99.32% validation,
  99.74% test-2025, and 100% test-2026. Coverage clears; publication as-of does
  not.
- EXP-005's narrower audit reverified the 79 selected USD-M BTCUSDT 1m
  archives plus all 11,770 D-022 inputs. Exact flow availability is 99.82% /
  99.83% / 99.77% / 100% and seven-M0-plus-flow joint availability is 99.58% /
  99.83% / 99.77% / 100% for development / validation / test-2025 /
  test-2026-01..07, with no zero-coverage month.
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
- Exact D-033 audit: spot switches ms to us at 2025-01; USD-M remains ms. Spot
  has 15 gap runs / 2,325 missing minutes and 8 nonstandard raw close times;
  USD-M 1m is complete. Metrics has 145 nominal missing slots, 143 off-grid
  rows, two conflicting duplicate timestamps, and 2,866 raw out-of-order rows
  across official daily files; audit normalization sorts within each daily file
  while preserving that diagnostic. Funding has 3,224 millisecond-jittered
  `calc_time` values and no missing nominal settlements.
- Metrics/funding bulk archives have source/event time and 2026 retrieval time,
  not historical publication/receive time or an authoritative latency bound.
  D-033 therefore blocks the complete M1 rung before fit. Do not invent a lag.
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
- The challenger-history debt is closed. `challenger_history.*` now derives
  from `index_clusters.json` with D-019 provenance.

### EXP-001: CLOSED, FAIL (2026-08-24)

Phase 1 tractable share 39.06%; Phase 2 combined reconstruction accuracy 8.02%
(663 isolated events evaluable on Oct cascade; cross-margin unobserved without
wallet state). D-018 demotion: HL challenger is realized-mass diagnostics only.
Artifacts: `reports/exp001/stratification_census.*`, `reports/exp001/reconstruction_*`.

### P3 / EXP-002: CLOSED, NULL (2026-08-25)

`cex_oi_cohort_v0` is parked and directionally negative. Reports bank
`d591f9b`; verdict bank `1b249da`. No floor relaxation, reskin, or fuel retry.

### P5 / D-032: BANKED (2026-08-25)

- The original positive-cluster-only EXP-004 unit was invalid: it selected on
  the outcome and had no non-events. It was superseded before any fit, score, or
  validation/test effect inspection.
- Correct unit: causal D-022 states at fixed UTC-hour interval ends. Outcomes are
  joint first-cause `{UP, DOWN, NONE}` with opposite direction an explicit
  competing event; ambiguous bars and future feed gaps are unscored and counted.
- Precondition rule: require
  `abs(log(P_T/P_{T-15m})) < log(1.005)` on exact index endpoints. Same support
  for fixed and volatility-twin labels.
- Probability rows weight 1; alert episodes weight 1 for precision; direction x
  horizon event clusters weight 1 for recall/lead time. Family-wide UTC-week
  blocks preserve linked rows. Brier/calibration and fixed-budget alert metrics
  replace event-only Spearman.
- Contract/code bank: `2319b07`. D-022 challenger inventory bank: `54e7166`.
  The sidecar cites full commit `2319b07e8dc34336e943c09cac657c3a7211f613`,
  config hash `c2b240bf...`, and input/output hashes.
- Regenerated cluster-history counts (1h / 4h): price `1658 / 1935`, CEX
  history `983 / 1313`, HL impact context `556 / 820`, HL fills `164 / 287`.
- At the P5 close, EXP-004 remained PLANNED with empty Result/Verdict. D-034
  later supplied a separate M0-only authorization; see D-035 below.

### D-033 / EXP-004 implementation contract: BANKED, UNSCORED (2026-08-25)

- Exact contract: `docs/briefs/2026-08-25-p6-implementation-freeze.md`.
  Contract commit `21fbfd4`; official-metrics source-order correction
  `04edc6b`; D-019 audit evidence commit `c430f8f`.
- M0 is exactly seven price/calendar columns. M1 adds exactly OI level, realized
  funding, same-venue premium, and taker-flow variance compression. No fuel or
  parked proxy enters either rung.
- Future estimator is deterministic three-cause ridge multinomial logistic,
  `NONE` reference, development-only scaling, fixed `lambda=1e-4`, and exact
  `M0_COMMON`/M1 complete-case support. Mechanical PASS/FAIL/NULL/BLOCKED rules,
  volatility/session/morphology slices, and `NEWS_NOT_AVAILABLE` are frozen.
- The source-only audit verified all 1,962 manifest entries and on-disk hashes.
  Every coverage floor passes and no full month has zero joint coverage. OI and
  funding nevertheless lack historical publication evidence; complete M1 is
  `BLOCKED_ASOF`. Premium and taker flow clear D-017 interval-end causality.
- At the D-033 close, no risk-set builder, estimator, fit, threshold, score, or
  validation/test effect existed. D-034/D-035 later superseded that stop only
  for the exact frozen M0 rung.

### D-034 / D-035 / EXP-004 M0: CLOSED, NULL (2026-08-25)

- Pre-OOS implementation SHA:
  `680f2af101f88b55e761945390f6da020c9e9a71`. The preceding identical tree
  passed the real development-only firewall on the data host: all 11,770 D-022
  inputs verified, only the development period was present, four models
  converged below the `1e-6` gradient gate, and no OOS outcome was constructed.
- The exact clean-SHA OOS run consumed one local receipt and was not rerun.
  Evidence commit: `826ea19e82ab05b10d7ee64830627fe763e8e4d8`.
  Verdict/status commit: `87044541517d46bb38a56dbcb4d4b0a3e053fb0f`.
- M0 disposition is **NULL**. Family Brier skill fixed/twin was
  `3.8968% / 1.9171%` validation, `6.9481% / 1.4413%` test-2025, and
  `6.2367% / 1.0884%` test-2026-01..07. These clear the point skill floor but
  cannot rescue the rung: cluster recall was below 10% in every primary cell,
  with additional precision, lead, and minimum-cluster misses.
- Banked artifacts: `reports/exp004/m0_frozen_state.json`,
  `m0_result.{json,md}`, and `m0_result.provenance.json`. Provenance names the
  pre-OOS SHA, exact config hash, verified source manifest, runtime, and output
  hashes. No machine-local path is committed.
- M1 remains `BLOCKED_ASOF` and unimplemented. D-035 authorized no M1, M2+,
  P4/EXP-003, feature addition, rerun, or other ladder rung; D-036 below records
  the later separate P4 source-gate commission.

### D-036 / EXP-003 P4: CLOSED, BLOCKED_SOURCE (2026-08-25)

- Implementation-ready v4 contract commit:
  `8e23b80366c9414d754afd84dbbf49e13c4e0983`. Pre-effect evidence commit:
  `23c838e5721bdde90b4797fda72b51ec9950fa38`. Status/verdict commit:
  `82a9d944d3804541599f1176415fbbfe5f02bada`.
- All 1,168 available `asset_ctxs` files share the exact 12-column schema and
  expose `mark_px`, `impact_bid_px`, and `impact_ask_px`, but no impact-notional
  version or receive/publication timestamp. One date, 2026-07-08, is absent.
- Available official contract captures state 20,000 USDC for BTC/ETH. Fixed
  source-only L2 walks instead reproduce ~5,000 USDC through 2023-05-30 and
  20,000 USDC after a transition in `(2023-05-31T01:32:00Z,
  2023-05-31T01:32:22Z]`. The early regime has no authoritative versioned spec.
- Raw context `time` is a point-snapshot stamp with off-grid observations; the
  official archive/API does not prove public availability no later than `T`.
- Both source gates fail. No fills, exact-match eligibility census,
  VWAP/slippage, effect, bootstrap, implementation SHA, or one-shot receipt was
  created. Do not narrow history, infer the schedule, substitute trailing
  realized impact, or call this FAIL/NULL.

### D-037 / EXP-005 flow replication: CLOSED, NULL (2026-08-25)

- Checkpoint A evidence commit `79851be` cleared exact USD-M interval semantics,
  T-5m causality, archive/input hashes, and all period coverage floors before
  labels or effects.
- The real development firewall passed at candidate `3e71902`: every source
  row, candidate row, passage, and cluster passed downstream was strictly
  pre-2024; `kappa=0.771724`; four development support IDs and eight fresh
  converged models were frozen. No OOS score support was frozen. External
  envelope SHA-256: `dbae564b...`; frozen-state SHA-256: `317bdc29...`.
- Empty pre-OOS seal SHA:
  `7fa0709011f451d0fc5ef95b5f4b5e7baf8152ed` (tree-identical to the
  development candidate). One local experiment-wide receipt was consumed and
  completed valid; no OOS refit or retry occurred.
- Evidence commit: `7ab09aa62b4392c61aa93d40752ca1ec3bd86efb`.
  Fixed/twin family Brier lift was `0.1785% / -0.0040%` validation,
  `0.2180% / 0.0309%` test-2025, and `0.1346% / -0.0305%`
  test-2026-01..07. All miss the +1% PASS floor; the stable -1% FAIL rule is
  false; multiple primary alert gates miss. Mechanical verdict: **NULL**.
- Park exact D-033 flow compression without another window, transform,
  threshold, or run. It does not shrink/unblock M1 or authorize M2+.

### D-012 derived HL fills store

P0 BANKED (main `656c4fb`). Canonical analytical source:
`{data_root}/derived/hyperliquid/fills/v1/all_fills`, Hive-partitioned by UTC
`date=YYYY-MM-DD/hour=HH` with `zstd` Parquet by default. Install opt-in deps
with `python -m pip install -e '.[dev,hyperliquid,analytics]'`.

Run on the data host, supplying the external Oracle data root from the local
handover:

```bash
python scripts/build_hl_btc_liquidations.py \
  --data-root <oracle-data-root> \
  --overwrite

python scripts/run_hl_parquet_census_parity.py \
  --data-root <oracle-data-root>
```

The builder writes `manifest.json` and `manifest.provenance.json` beside the
derived table under the data root. The parity gate reads Parquet via DuckDB
only, streams per `source_path` to avoid a global-sort OOM, replays the EXP-001 Phase 1 census state machine, and emits
`reports/infra_hl_parquet_v1/parity.{json,md}` plus a D-019 sidecar. In cloud
or CI without the data host, the parity script writes a `MISSING_DATA` report
and exits non-zero; do not invent passing parity numbers.

### Next work (in order)

Authoritative sequence remains `docs/glide_path.md`. There is no active
implementation or science commission after this seat close.

1. **Next judgment point:** Chair reviews the banked EXP-005 `NULL` at evidence
   commit `7ab09aa62b4392c61aa93d40752ca1ec3bd86efb`. Exact D-033 flow
   compression is parked; no same-family retry or window/transform change is
   authorized. Nothing self-starts.
2. EXP-003 remains `BLOCKED_SOURCE`. A future quoted-impact attempt requires
   authoritative versioned notional history and row-level as-of semantics;
   narrowing to the later regime is a contract change.
3. The earlier EXP-004 M0 verdict remains NULL. If qualifying M1 publication
   evidence is ever supplied and a new commission is granted, apply D-033
   unchanged. Do not shrink M1, invent a lag, substitute
   Hyperliquid/parked fuel, or reuse the consumed M0 execution authorization.
4. No M1, M2+, EXP-003 rescue, replacement impact proxy, fuel retry, new feature
   family, dashboard, live service, or trading work is active.

### Glide path (authoritative sequence)

Active research sequence is `docs/glide_path.md` (v1). **P3 BANKED NULL**
(reports `d591f9b`, verdict `1b249da`). **P5 BANKED** (corrected D-032;
contracts `2319b07`, inventory `54e7166`). **D-033 contract/audit BANKED**
(`21fbfd4`, `04edc6b`, `c430f8f`). **EXP-004 M0 BANKED NULL** (pre-OOS
`680f2af`, evidence `826ea19`, verdict `8704454`). **M1 BLOCKED_ASOF; all later
rungs unauthorized.** **EXP-003 P4 BANKED BLOCKED_SOURCE** (contract
`8e23b80`, evidence `23c838e`); no census or score. **EXP-005 BANKED NULL**
(pre-OOS `7fa0709`, evidence `7ab09aa`); exact flow replication parked.
Census: `reports/p1_eligibility_census.json`. No M2.


### Seat note (2026-08-25)

Codex completed EXP-005 through its exact-SHA one-shot, banked the mechanical
`NULL`, synchronized the public status surface, and stopped. The next seat
inherits no active implementation commission. Thin orchestration is
provider-neutral: the lead owns research judgment; subagents perform only
fenced mechanical work.

### Operating notes

- Thin orchestration per AGENTS.md: select subagents by required capability,
  reliability, and cost/latency with tight specs; lead seat reviews everything;
  contracts, experiment semantics, ledger verdicts, and decisions are never
  delegated. Property tests against `labels.first_passage` are the pattern for
  any new labeller.
- An external advisory/red-team seat exists (read-only); its first 2026-08-23
  review produced D-016..D-019, EXP-001, and the D-017 timestamp fix; its
  second (same day) endorsed the Kraken escalation, requested the blind
  D-022 freeze, a D-021 interpretation caveat, D-019 provenance sidecars on
  committed artifacts, and doc-sync hygiene (all executed or in flight).
- Venue APIs can serve censored tape: the Kraken Trades API omitted a
  906-second cascade window that official bars contained; always validate
  trades-derived bars against an official overlap before trusting them.
- Run `python -m unittest discover` and `ruff check .` (use repo venv) before
  handing off. 281 tests passed (7 skipped) and Ruff passed before the EXP-005
  status close; rerun after any handover-only commit.
- Known open decisions are listed at the bottom of `docs/DECISIONS.md`. The
  precondition impulse, large-cluster weighting, and D-026 twin estimator are
  closed by corrected D-032.
