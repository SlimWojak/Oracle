# CTO seat handover

Agent-to-agent orientation. Update this file before every seat rotation.
Read order for an incoming seat: `AGENTS.md` -> this file -> `EXPERIMENT_LEDGER.md`
-> `docs/DECISIONS.md`.

Operational access details (hosts, accounts, profiles, local paths, session
identifiers) live in `docs/HANDOVER_LOCAL.md` on the canonical workstation.
That file is gitignored and must never be committed; this repository is public.

## State as of 2026-08-23 (seat 1)

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

Done: acquisition (above); event catalogue built and committed
(`reports/exp000/`): 1,679 (1h) / 1,940 (4h) independent clusters,
pseudo-replication 82:1 / 338:1, direction balanced, ambiguity negligible.

Remaining for verdict:
1. Propose chronological dev/validation/test split boundaries (regard regime
   diversity; per-year cluster counts are in the catalogue).
2. Per-fuel-challenger usable history table (D-016 common-support rule now
   governs how these histories are compared).
3. Kraken replication gate for labels (D-013); not started.

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
- An external advisory/red-team seat exists (read-only); its 2026-08-23 review
  produced D-016..D-019, EXP-001, and the D-017 timestamp fix.
- Run `python -m unittest discover` and `ruff check .` (use repo venv) before
  handing off. 54 tests green at handover.
- Known open decisions listed at the bottom of `docs/DECISIONS.md`.
