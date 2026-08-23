# CTO seat handover

Agent-to-agent orientation. Update this file before every seat rotation.
Read order for an incoming seat: `AGENTS.md` -> this file -> `EXPERIMENT_LEDGER.md`
-> `docs/DECISIONS.md`.

Operational access details (hosts, accounts, profiles, local paths, session
identifiers) live in `docs/HANDOVER_LOCAL.md` on the canonical workstation.
That file is gitignored and must never be committed; this repository is public.

## State as of 2026-08-23 late evening (seat 2)

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
- Coinbase BTC-USD 1m candles 2019-12..2026-08: acquisition in flight on the
  data host at handover-writing time (public API, ~11,700 tiled windows).

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

### EXP-000 status (RUNNING)

Done: all acquisition (above); event catalogue + per-cluster inventory
committed (`reports/exp000/`): 1,679 (1h) / 1,940 (4h) independent clusters,
82:1 / 338:1 pseudo-replication; per-challenger usable history table
(D-016); D-020 accepted (no HL-fills predictive ladder this cycle); Kraken
replication gate (D-013/D-021) implemented, corrected (time-aware venue
labeller) and run: 5.90% (1h) / 4.26% (4h) disagreement, both above the 2%
line, disputes overwhelmingly near-misses (median best Kraken move ~1.94%).
ESCALATION TRIGGERED: median-of-three index required. D-022 (index
semantics) frozen blind before Coinbase data was inspected.

Remaining for verdict:
1. Finish Coinbase candle acquisition + audit (in flight).
2. Build the D-022 consolidated index in the normalization layer; rebuild
   the catalogue on it; produce the D-022 sensitivity report
   (Binance-only vs consolidated churn).
3. Re-run the D-021 gate context only if semantics demand (the index
   supersedes per-event VENUE_DISPUTED flagging).
4. Propose chronological split boundaries on the consolidated catalogue.
5. Record the EXP-000 verdict and CLOSE the experiment (advisor: do not let
   the ledger become a diary).

### Next work after EXP-000 verdict

- EXP-001 (PLANNED, see ledger): Hyperliquid fuel-surface reconstruction
  feasibility. This gates any "HL-observed fuel" feature per D-018. It comes
  before fuel feature construction, not after.
- Normalization layer for fills and asset_ctxs (tested modules, manifests,
  timestamp audits per DATA_CONTRACT). Fills are all-asset; filter BTC at
  normalization, keep raw intact.
- Construct validation design (RESEARCH_CONTRACT gates): fuel vs realized
  liquidation mass with book-hitting/backstop split; impact proxies vs
  realized slippage.
- Pre-model descriptive gates (armed-quadrant occupancy, trailing-path
  confound) before any M4 interaction work.

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
  handing off. 101 tests green at last check.
- Known open decisions listed at the bottom of `docs/DECISIONS.md`.
