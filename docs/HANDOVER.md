# CTO seat handover

Agent-to-agent orientation. Update this file before every seat rotation.
Read order for an incoming seat: `AGENTS.md` -> this file -> `EXPERIMENT_LEDGER.md`
-> `docs/DECISIONS.md`. Founding session chat id: dfba2fe1-f713-4a2f-94bf-93437dc0a900.

## State as of 2026-08-23 (seat 1)

### Topology and access

- Workstation: user's MacBook, canonical repo seat, this repo at `~/Oracle`.
- Data host: `dexter` (SSH alias configured; DGX Spark, aarch64, 119GB RAM,
  2.4TB free NVMe, tmux, uv, aws-cli). Repo clone `~/oracle`, venv `.venv`,
  data root `~/oracle-data` (raw immutable; see `DATA_CONTRACT.md`).
- Do not touch other directories on dexter (aura, galileo, exo-test).
- AWS: profile `oracle` (login-based, project account 748332174606), profile
  `oracle-data` (long-lived scoped IAM user `oracle-data-reader`, S3 read on
  the two Hyperliquid buckets only; present on workstation and dexter).
  Requester-pays works after an SCP edit in the org management account
  (region floor + us-east-1 S3 reads). Org: management 499038634275,
  identity 576513731662, project 748332174606.

### Data on hand (dexter, `~/oracle-data/raw/`)

- `binance_vision/`: spot+UM perp 1m klines and funding 2020-01..2026-07,
  UM daily metrics 2021-12..2026-08. 1,962 files, checksum-verified,
  manifested. 99.97% bar coverage.
- `hyperliquid/asset_ctxs/`: per-minute contexts (incl. quoted impact prices,
  OI, premium) 2023-05-20..present, ~9GB.
- `hyperliquid/node_fills*/`: full fill history 2025-05-25..present, two
  formats (old `node_fills/hourly` to 2025-07-27, then
  `node_fills_by_block/hourly`), ~520-640GB. Pull launched 2026-08-23 ~13:05
  local in tmux session `hl-stage2`; log
  `~/oracle-data/manifests/hl_stage2_20260823.log`.
- `hyperliquid/samples/`: two schema-inspection fill hours (one per format,
  incl. 2025-10-10 hour 21, the record cascade).

### Verified schema facts (load-bearing)

- Fill records carry `liquidation: {liquidatedUser, markPx, method}` with
  method in {market, backstop}; ADL appears as dir "Auto-Deleveraging".
  Dedupe liquidation totals by the liquidatedUser leg (object rides both legs).
- New fill format wraps events in blocks with `local_time` (receive) and
  `block_time` (source) - keep both per DATA_CONTRACT.
- Binance klines stamp interval START; Binance metrics dumps stamp interval
  END (-5 min realignment required, see DATA_CONTRACT). Kline open_time is ms
  before 2025-01, us after (loader handles it).
- lz4 python package installed in dexter venv for fill decompression.

### EXP-000 status (RUNNING)

Done: acquisition (above); event catalogue built and committed
(`reports/exp000/`): 1,679 (1h) / 1,940 (4h) independent clusters,
pseudo-replication 82:1 / 338:1, direction balanced, ambiguity negligible.

Remaining for verdict:
1. Propose chronological dev/validation/test split boundaries (regard regime
   diversity; per-year cluster counts are in the catalogue).
2. Per-fuel-challenger usable history table (HL observed: fills from
   2025-05-25, impact prices from 2023-05-20; CEX-inferred: metrics from
   2021-12; vendor: unresolved, likely blocked on point-in-time honesty).
3. Kraken replication gate for labels (D-013): kraken market data available
   via workstation MCP tools or CSV dumps; not started.

### Next work after EXP-000 verdict

- Normalization layer for fills and asset_ctxs (tested modules, manifests,
  timestamp audits per DATA_CONTRACT). Note fills are all-asset; filter BTC
  at normalization, keep raw intact.
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
- Run `python -m unittest discover` and `ruff check .` (use repo venv) before
  handing off. 51 tests green at handover.
- Known open decisions listed at the bottom of `docs/DECISIONS.md`.
