# Experiment ledger

This file is append-only in meaning. Existing experiment records may receive factual
corrections with an explicit correction note; verdicts are not silently rewritten.

## Status vocabulary

- `PLANNED`
- `RUNNING`
- `PASS`
- `FAIL`
- `NULL`
- `BLOCKED`
- `INVALID`

## EXP-000 — Data feasibility and independent-event audit

- **Status:** PASS (closed 2026-08-24)
- **Correction note (2026-08-23):** the status line originally read "free
  Binance Vision dumps only, no requester-pays spend"; superseded when the user
  approved the Hyperliquid requester-pays pull recorded in the result trail.
- **Question:** Is there sufficient point-in-time data and independent +/-2% event
  coverage to test the v0 contract without pseudo-replication?
- **Inputs:** Consolidated BTC index candidate feeds and availability metadata for
  fuel, impact, and ignition sources.
- **Method:** Build fixed 1h/4h first-passage labels; identify ambiguous bars; cluster
  adjacent labels into independent events; produce source-by-time coverage matrix.
- **Required outputs:** Timestamp counts, independent cluster counts, direction and
  horizon breakdown, gap report, proposed time splits, unresolved data decisions,
  per-fuel-challenger usable point-in-time history (the Hyperliquid fill log
  begins 2025-05-25; vendor as-of history is unverified), and an estimated size
  and cost of the requester-pays Hyperliquid S3 pull before any spend.
- **Pass condition:** Coverage supports at least one honest development/validation/
  test design or clearly identifies a justified discovery-only alternative.
- **Failure meaning:** Revise scope or data acquisition before feature engineering.
- **Result:** In progress. 2026-08-23: Binance Vision acquisition complete
  (1,962/1,962 files, zero missing, zero checksum failures; spot+perp 1m klines
  and funding 2020-01..2026-07, daily metrics 2021-12..2026-08). Hyperliquid
  requester-pays S3 access is BLOCKED by an organization-level guardrail on the
  new-experience AWS account (cross-account S3 denied above IAM; confirmed with
  scoped IAM user and an arxiv requester-pays control). HL pull sizing deferred
  until the SCP is lifted from the org management account.

  2026-08-23 catalogue run (`reports/exp000/`): 3,459,435 one-minute bars,
  2020-01-01..2026-07-31, 99.97% coverage (15 gaps, 2,325 missing minutes, all
  material gaps pre-2022). Pseudo-replication confirmed and quantified: 1h
  horizon has 136,952 positive timestamps collapsing to 1,679 independent
  clusters (82:1); 4h has 655,883 collapsing to 1,940 (338:1). Direction is
  balanced (1h pure clusters: 560 up / 568 down; 551 mixed). Every calendar
  year contains 98-440 clusters, so multiple contiguous OOS periods are
  feasible. Ambiguous labels are negligible (16 and 19). Cluster duration is
  heavy-tailed (1h median 83 min, max 9.2 days). Remaining before verdict:
  proposed chronological splits, per-fuel-challenger usable history, HL pull
  sizing (blocked on AWS SCP).

  2026-08-23 (later): AWS SCP unblocked (region floor widened to ap-northeast-1;
  S3 reads whitelisted in us-east-1). Hyperliquid requester-pays sizing:
  `asset_ctxs` (per-minute contexts incl. quoted impact prices, all assets)
  2023-05-20..present, 1,169 daily files, ~6 GB, ~$0.60 egress; `market_data`
  L2 book (BTC-only slice, hourly ~0.9 MB) 2023-04-15..present, ~29 GB, ~$3;
  `node_fills/hourly` (old format) 2025-05-25..2025-07-27, 64 days x ~0.8 GB
  ~51 GB, ~$6; `node_fills_by_block/hourly` 2025-07-27..present, 393 days x
  ~1.2-1.5 GB, ~470-590 GB, ~$54-67. Full fill history therefore ~$60-75 of
  the $100 credit. Staged plan: Stage 1 (executed) asset_ctxs full plus two
  sample fill hours for schema inspection; Stage 2 (user sign-off required)
  full fill history; l2Book BTC slice cheap and deferred to need.

  Stage 1 complete (asset_ctxs ~9GB; samples verified: fills carry
  liquidation.liquidatedUser and method in {market, backstop}; ADL tagged;
  dedupe by liquidated-user leg confirmed viable). Stage 2 full fill pull
  approved by user and launched 2026-08-23; result to be recorded on
  completion.

  2026-08-23 (advisor review): anchor timestamps in the catalogue were stamped
  at kline interval start although labels use the bar close. Fixed per D-017
  (decision timestamp = interval end); catalogue rebuilt. Counts unchanged;
  all anchor and passage timestamps shifted +60s.

  Stage 2 complete (2026-08-23 05:06-06:11Z, 65 min). Full Hyperliquid fill
  history on the data host: old format 1,507 hourly files ~30GB
  (2025-05-25..2025-07-27), by-block format 9,405 hourly files ~240GB
  (2025-07-27..2026-08-23 hour 4). Verified by dry-run re-sync against S3:
  zero missing objects in either prefix (the only pending object was the hour
  published after the sync's listing pass). File counts below theoretical
  hour counts reflect hours absent from the archive itself, not download
  failures. Actual size ~270GB vs the ~520-640GB estimate; the per-day
  estimate had extrapolated from the record-cascade sample hour, so egress
  spend came in near half of budget. All EXP-000 data acquisition is now
  complete.

  2026-08-23 (seat 2): D-020 accepted — the HL-fills challenger runs no
  predictive ladder this cycle (its usable window lies wholly inside any
  regime-diverse test region). Per-cluster inventory committed
  (`reports/exp000/clusters.json`, deterministic rebuild, counts unchanged)
  and the per-fuel-challenger usable history table built from it
  (`reports/exp000/challenger_history.{json,md}`): price-only 1,679/1,940
  clusters (1h/4h); CEX-inferred from 2021-12-01, 991/1,329; HL
  impact-context from 2023-05-20, 561/835; HL fill tape from 2025-05-25,
  163/292 (construct validation and EXP-001 only per D-020). Vendor
  challenger has no verified as-of history. In flight: l2Book BTC-only
  slice pull (hyperliquid-archive `market_data`, ~29GB est., ~$3) and
  Kraken XBTUSD 1m OHLCVT acquisition for the D-013 replication gate.
  Remaining before verdict: Kraken replication run, split proposal.

  2026-08-23 (seat 2, later): l2Book BTC slice pull complete (07:14-07:44Z,
  30 min): 28,304 hourly `l2Book/BTC.lz4` files, ~22GB, dates
  2023-04-15..2026-08-01. Verified by dry-run re-sync: zero missing objects
  under the BTC filter. The `hyperliquid-archive` market_data prefix trails
  the present (last published date 2026-08-01), which still fully covers the
  catalogue window ending 2026-07-31. The ~600-hour shortfall vs theoretical
  hours is hours absent from the archive, matching the fill-pull pattern.

  2026-08-23 (seat 2, later): Kraken XBTUSD acquisition for the D-013
  replication gate complete (delegated; lead-reviewed). Official OHLCVT 1m
  CSVs: master export through 2025-12-31 plus Q1 2026 quarterly (both
  Drive-quota-blocked programmatically; retrieved by manual user browser
  download, rsynced to the data host, sha256-verified end to end). Combined
  official bars 2013-10-06..2026-03-31, 3,234,282 rows inside the catalogue
  window, exact 60s continuity at both file seams. Raw public-API trade
  pages: 2026-01-01..2026-04-01 (5,762 pages, overlapping official Q1 bars
  as a deliberate bar-construction validation corpus) and
  2026-04-01..2026-08-01 (6,466 pages); zero rate-limit or error pages.
  Kraken structural missing minutes (no-trade bars absent by construction):
  30,186 in 2020 falling to 2,362 by 2025 — replication semantics must
  treat absent bars as reduced evidence, not disagreement. Manifest with
  full hash tables on the data host; fetch script and tests committed.
  Apr-Jul 2026 has no official bars; replication over that span waits on
  the normalization-layer bar construction from raw trades.

  2026-08-23 (seat 2, later): D-021 accepted (frozen replication semantics),
  then corrected before any committed result: the initial segment-restricted
  venue labeller under-detected passages in gap-dense years (2020 Kraken:
  24,261 segments, median 6 bars), inflating 4h disputes to a diagnostic
  22%. Corrected to a time-aware wall-clock-window labeller (identical
  semantics on contiguous data; correction note in D-021). Gate results on
  the corrected code (`reports/exp000/replication_gate.{json,md}`,
  repo 401dc6a): 1h — 1,532 replicated, 96 disputed, 13 sparse, 38 pending;
  disagreement 5.90%. 4h — 1,754 replicated, 78 disputed, 24 sparse,
  84 pending; disagreement 4.26%. Both exceed the 2% D-013 escalation
  threshold. Near-miss diagnostic on disputed clusters: median best Kraken
  same-direction move 1.94-1.95%; 88/96 (1h) and 77/78 (4h) reached at
  least 1.8%; only one cluster below 1.0%. Disputes are therefore marginal
  barrier-crossing disagreements, not absent moves: labels are
  venue-sensitive at the barrier margin. VERDICT per D-013: a
  median-of-three consolidated index is REQUIRED before predictive work.
  Third venue selection is an open decision (Coinbase BTC-USD spot is the
  leading candidate: largest USD spot venue, free public data).
  PENDING_BARS clusters (2026-04..07) await trades-derived Kraken bars from
  the normalization layer.

  2026-08-23 (seat 2, later): Kraken trades-to-bars construction built to a
  frozen lead spec (delegated implementation, lead-reviewed, committed
  970106e) and construct-validated: derived Q1 2026 bars match the official
  OHLCVT CSV on all 129,509 rows exactly (zero OHLC/trades differences,
  volume at float epsilon). Validation initially exposed one 906-second
  hole INSIDE a raw Trades-API page (2026-02-20 13:38:47-13:53:53Z, a
  cascade window served censored by the API while present in official
  bars); a live refetch recovered it (2 append-only patch pages, manifest
  note on the data host). All other intra-page tape gaps in 2026-01..07
  coincide with scheduled maintenance halts absent from official bars too.
  Trades-derived bars for the official-bar-free span rebuilt from committed
  code at 970106e: 175,578 rows, 2026-04-01..2026-07-31 (per-month missing
  minutes 26/28/18/30, maintenance-shaped). Coinbase BTC-USD 1m candle
  acquisition (third index venue) in flight on the data host.

  2026-08-23 (seat 2, late): Coinbase acquisition complete (public Exchange
  API, 11,688 inclusive-boundary tiled windows, 2h40m, zero retries, zero
  duplicate timestamps): 3,504,259 bars 2019-12-01..2026-07-31 with 2,141
  structural missing minutes total (2020: 648 vs Kraken's 30,186). Largest
  holes 391/349/277 min (2026-05-08, 2025-10-25, 2023-03-04), listed in the
  data-host manifest with per-file sha256s. Fetch script and tests committed
  (07963f8). All three D-022 index members are now on the data host;
  consolidated-index construction is next, followed by the sensitivity
  report, split proposal, and EXP-000 verdict.

  2026-08-24 (seat 2): D-022 consolidated index built and catalogue rebuilt
  on it (`reports/exp000/index_*`, `SENSITIVITY.md`, provenance sidecars).
  Index grid 2020-01-01..2026-07-31: 3,461,652 bars, only 108 missing
  minutes (vs 2,325 Binance-only — the >=2-of-3 union is more complete than
  any member); 98.4% of bars are 3-of-3; 0.87% (1h) / 1.02% (4h) of positive
  anchors sit on 2-of-3 bars. Sensitivity vs Binance-only labels (aligned
  2020-01-01 start): 1h 1,679 -> 1,658 clusters (1,630 retained, 0 direction
  flips, 49 removed, 17 added, median |start shift| 0s, p90 180s); 4h
  1,940 -> 1,935 (1,897 retained, 0 flips, 43 removed, 26 added). Removals
  skew to 2020-21, consistent with the gate's finding that disputes were
  marginal single-venue barrier events. The consolidated catalogue
  (`index_clusters.json`) is now the label population for split design;
  remaining before verdict: split boundaries, then close EXP-000.

- **Verdict (2026-08-24): PASS.** D-023 accepted (chronological splits:
  development 2020-01-01..2023-12-31, validation 2024, final test
  2025-01-01..2026-07-31 as two contiguous OOS periods; straddle-drop
  boundary rule; per-challenger ladders share the final test per D-016).
  Coverage supports an honest development/validation/test design on the
  consolidated D-022 index: 1,658 (1h) / 1,935 (4h) independent clusters
  with venue-robust labels (zero direction flips under consolidation),
  per-fuel-challenger usable histories recorded
  (`reports/exp000/challenger_history.*`), pseudo-replication quantified
  and controlled by D-014 clustering, and the D-013 replication escalation
  resolved by construction rather than exclusion. Experiment closed.
- **Limitations carried forward:** validation year is thin (235 one-hour
  clusters); the volatility-normalized barrier twin remains an open
  decision; large-cluster weight policy must be settled before M2 scoring;
  2026-04..07 Kraken index bars derive from the raw trade tape (exact-
  validated methodology, but no official bars exist for that span); the
  challenger-history table still reflects the Binance-only catalogue and
  should be regenerated from `index_clusters.json` before ladder work.

## EXP-001 — Hyperliquid fuel-surface reconstruction feasibility

- **Status:** FAIL (closed 2026-08-24)
- **Frozen question:** Can a causal pre-state liquidation topology at time t be
  honestly reconstructed from available Hyperliquid data, given that
  cross-margin liquidation prices depend on account value, other positions,
  funding, and margin state rather than the wallet's fills alone?
- **Hypothesis:** A tractable subset of liquidated BTC notional — wallets whose
  pre-event state is inferable without L1 account snapshots — carries enough
  coverage-weighted mass that an HL-observed fuel surface is viable as a partial
  surface with a documented bound; cross-asset wallets are stratified out rather
  than modelled in v0.
- **Data manifest:** Hyperliquid `node_fills` + `node_fills_by_block` hourly
  LZ4 on the data host (2025-05-25..catalogue end); `asset_ctxs` for mark/funding
  in the reconstruction phase; optional `replica_cmds` only if Phase 2 fails and
  is sized before spend.
- **Development period:** Full fill tape 2025-05-25..2026-07-31 for Phase 1
  census; Phase 2 reconstruction trains on tractable strata outside held-out
  cascade windows.
- **Validation period:** — (feasibility experiment; no predictive ladder).
- **Final test period:** Held-out cascade windows below (reconstruction error only).
- **Features available as of:** Fill tape from 2025-05-25; asset_ctxs from
  2023-05-20 (used only in Phase 2 for tractable wallets).
- **Method (frozen 2026-08-24):** Two phases. Do not attack cross-margin
  reconstruction head-on; stratify first.

  **Event unit.** One deduped BTC liquidation event: a fill with `coin == "BTC"`,
  a `liquidation` object, and `user == liquidation.liquidatedUser` (liquidated-user
  leg only; the object rides both legs — dedupe before any count). Primary key:
  (`liquidatedUser`, `tid`). USD notional: `float(px) * float(sz)`.

  **Routing split (binding from first count).** Partition every event by
  `liquidation.method`: `market` (book-hitting) vs `backstop` (backstop-absorbed).
  Report both; construct-validation and fuel propagation tests use book-hitting
  mass; backstop mass is diagnostic only (RESEARCH_CONTRACT construct gate).

  **Stratification at event time t** (`fill.time` ms, liquidated user):
  1. **(c) cross-asset:** exists coin C ≠ `BTC` where the user's last known
     post-fill net position on C at or before t has `abs(position) >= 1e-8`
     (end position inferred from `startPosition`, `side`, and `sz`; not raw
     `startPosition`, which is pre-fill and misclassifies closed alt positions).
  2. **(a) BTC-only isolated:** not (c) and `dir` matches `Liquidated Isolated *`.
  3. **(b) BTC-only cross-margin:** not (c) and (`dir` matches `Liquidated Cross *`
     OR `method == market` with `dir` in {`Close Long`, `Close Short`} on the
     liquidated-user leg — the dominant market-liquidation tag on the tape).

  Tractable strata = (a) + (b). Stratum (c) is excluded from reconstruction;
  its notional sets the coverage bound on any partial surface.

  **Phase 1 — stratification census (full tape).** Stream all hourly fill files;
  classify every deduped BTC liquidation event; report event counts and USD
  notional by stratum and by `method`; tractable-share =
  `(notional_a + notional_b) / total_btc_liq_notional`. Artifacts under
  `reports/exp001/`.

  **Phase 2 — reconstruction (tractable strata only).** On held-out cascade
  windows, for strata (a) and (b) separately: infer pre-state BTC liquidation
  threshold from cumulative fills plus `asset_ctxs` mark/funding series; compare
  implied liquidation price at t−ε to observed `liquidation.markPx` on the event
  fill (per-event ground truth). Margin wallet balance remains unobserved; do
  not impute. If Phase 2 requires L1 account state, size `replica_cmds`
  requester-pays pull before spend (sample-hour trap: full fill pull was ~270GB
  actual vs ~520GB estimate).

  **Held-out cascade windows (UTC, inclusive hour boundaries):**
  - `2025-07-15T12:00:00Z` .. `2025-07-15T13:00:00Z` (old fill format; sample on hand)
  - `2025-10-10T21:00:00Z` .. `2025-10-10T22:00:00Z` (record cascade; by-block format)
  - `2025-08-05T14:00:00Z` .. `2025-08-05T15:00:00Z` (2025 final-test cluster hour;
    independent of the October cascade)

  Phase 2 trains on all tractable events outside these three hours.

- **Baselines:** — (feasibility only).
- **Metrics:** Phase 1 — tractable notional share; counts by stratum, direction,
  and `method`. Phase 2 — coverage-weighted fraction of tractable notional with
  `|implied_liq_px - markPx| / markPx <= 0.01` at ε = 1 fill before event;
  breakdown by stratum (a) vs (b) and by `method`.
- **Pass/fail contract:**
  - **Early demotion (Phase 1 only):** tractable notional share < 20% → FAIL;
    D-018 demotion path closed without cross-margin modelling or `replica_cmds`.
  - **Partial viability:** tractable share ≥ 50% with documented coverage bound
    (notional in (c) reported explicitly); does not alone PASS the experiment.
  - **PASS:** tractable share ≥ 50% AND Phase 2 coverage-weighted reconstruction
    accuracy ≥ 90% of tractable notional at the 1% relative-error tolerance on
    held-out windows.
  - **FAIL (after Phase 2):** tractable share ≥ 20% but Phase 2 accuracy below
    PASS threshold → per D-018 demote HL challenger; fills remain for realized-mass
    diagnostics.
- **Failure meaning:** Per D-018 the HL challenger is demoted from observed
  fuel to realized-mass diagnostics and construct-validation evidence for the
  other challengers. The fill tape retains value either way.
- **Result:** 2026-08-24 — design frozen; normalization scaffold and Phase 1 census
  complete (seat 3). **Phase 1 verdict (census v3, corrected code):** tractable
  notional share **39.06%** (`$9.02B` of `$23.09B` deduped BTC liquidation
  notional; 803,304 tractable events in strata a+b vs 659,390 cross-asset).
  Early demotion **not** triggered (≥20%). Partial viability at 50% **not** met.
  Census v1/v2 (tractable share 0.27%) invalid: pre-correction code on dexter
  from bad rsync. **Phase 2 verdict (2026-08-24, dexter):** held-out windows
  processed 14,279 tractable events (`$780M` notional). Combined coverage-weighted
  reconstruction accuracy **8.02%** at 1% relative-error tolerance (663 evaluated
  isolated events on 2025-10-10 hour 21; stratum b cross-margin 100% unobserved
  without account value). Below 90% PASS threshold; tractable share also below
  50% partial-viability bar. Per D-018, HL challenger demoted from observed fuel
  to realized-mass diagnostics and construct-validation evidence.
- **Verdict (2026-08-24):** FAIL. Honest pre-state liquidation topology cannot
  be reconstructed from fills + asset_ctxs alone at sufficient coverage-weighted
  accuracy. Fill tape retained for realized liquidation mass (book/backstop split)
  and construct validation of other challengers.
- **Artifacts:** `reports/exp001/stratification_census.{json,md}` (+ provenance);
  `reports/exp001/reconstruction_{window}.{json,md}` and
  `reports/exp001/reconstruction_summary.{json,md}` (+ provenance).
- **Correction notes (2026-08-24):** Phase 1 census v1 used pre-fill
  `startPosition` for cross-asset detection (inflated stratum c) and omitted
  market-method liquidations tagged `Close Long`/`Close Short` from tractable
  stratum (b). v2 uses post-fill net position and the market-close rule above.
- **Correction notes (2026-08-24, CTO bank):** Phase 2 `reconstruction_summary.provenance.json` records `repo_commit` `9d7bab3` (dexter working tree ahead of / not equal to the later bank commit). Counts and FAIL verdict are unchanged; treat that sidecar as run metadata for the dexter execution, not as the banked tip SHA. D-024 records the demotion as executed.


## EXP-002 — CEX-inferred directional fuel proxy (construct)

- **Status:** NULL (closed 2026-08-25; P3 construct gate; D-030)
- **Frozen question:** Does `cex_oi_cohort_v0` rank subsequent Hyperliquid book-hitting BTC liquidation notional on the **four primary 4h cells** `{up,down} × {(0,1%),[1,2%)}` when the named adverse-entry-distance band is far-edge traversed?
- **Hypothesis:** Time-varying adverse-band shape from quantity cohorts carries incremental within-band information beyond OI-only USD and trailing-price-path, on those four cells only.
- **Belief change:** PASS → M2-eligible **only for these 4h cells** (validates neither 1h nor `[2,4%)`). FAIL → this path dies. NULL → park. If any primary cell later falls below its coverage floor, NULL, not a redesign. Single cross-venue miss: *fails the observable construct gate; cause unresolved.*
- **Materiality:** F = equal-weight four-cell incremental Spearman. Shape: m3≥m1 in ≥3/4 cells, zero hard flips. Stability: Sep–Oct and Nov–Dec 2025, each ≥10/cell, defined F, positive challenger-minus-OI F. Floor: `max(0.10, 2*SE)` via `numpy.random.default_rng(20250825)`, **one family-wide** UTC-week draw carrying linked rows across both bands, B=1000, ddof=1. Coverage: construct-dev ≥10/cell, construct-val ≥15/cell. No further relaxation.
- **Data manifest:** Binance Vision UM 5-minute metrics (`sum_open_interest`, `sum_toptrader_long_short_ratio`; `sum_open_interest_value` for USD baseline only). D-022 index. HL fills Parquet v1 for target only. Census: `reports/p1_eligibility_census.json` + provenance.
- **Development period:** burn-in 2021-12 .. 2025-05-24 (unallocated opening stock; unscored). Construct-dev 2025-05-25 .. 2025-08-31.
- **Validation period:** 2025-09-01 .. 2025-12-31.
- **Final test period:** 2026-01-01 .. 2026-07-31 first look; 2026-08-01 .. 2026-12-31 second confirmation (D-029).
- **Features available as of:** last 5-minute metrics row with interval end ≤ T.
- **Method:** `docs/briefs/2026-08-25-p1-fuel-construct.md` v5.
- **Baselines:** OI-only USD; trailing-price-path (4h); `cex_oi_band_static` two-band weights (0.75, 0.25).
- **Metrics:** four-cell F and the PASS clauses.
- **Pass/fail contract:** mechanical NULL / FAIL / PASS in the v5 brief.
- **Result:** Phase B on dexter from `1df5bb2` / reports `d591f9b`. 172 targeted 4h cluster-rows. Construct-dev counts 12/12/23/23 (integrity True); construct-val 28/28/23/23 (integrity True). Dev family F_vs_oi=0.0165, F_vs_path=0.0201, F_static=0.0213. Val F_vs_oi=0.0607, F_vs_path=-0.0652, F_static=0.0986. Dev bootstrap B=1000, 14 weeks, 15 undefined draws → floor not locked. Val CI95 of both F statistics includes 0. Shape passed (4/4 m3≥m1, 0 hard flips). Both stability blocks passed (Sep–Oct F_vs_oi=0.250; Nov–Dec 0.133). Wall 1h02m, max RSS 3.22 GiB.
- **Verdict:** NULL. `cex_oi_cohort_v0` parked. No silent retry. No family redesign.
- **Limitations:** LSR reweights the same contract stock; adverse-entry is not a liq-price offset; 1h and `[2,4%)` are parked and non-confirmatory; construct-dev up cell is 12 (above the 10 floor, thin).
- **Artifacts:** brief v5; census + D-019 sidecar; D-030; reports bank `d591f9b`; verdict bank `1b249da`.
- **Correction notes:** v5 is the Chair four-cell feasibility correction (path-only census; no fuel/mass inspected). 12-cell family retired as theatre. 2026-08-25 Chair: treat NULL as **directionally negative**, not underpowered (misses materiality; loses to path and static; both val CIs include 0). No floor relaxation or LSR reskin.

## EXP-003 — Quoted book-walk impact proxy (construct)

- **Status:** PLANNED (P1 v3; **D-031 Accepted**; Chair 2026-08-25 deferred until after M0/M1 review)
- **Frozen question:** Do Hyperliquid published impact prices, at the venue-published impact notional, predict realized slippage in the immediately following epoch-aligned 60-second bucket?
- **Hypothesis:** Visible quoted walk ranks same-bucket matched slippage better than a trailing-range / trailing-vol baseline.
- **Belief change:** PASS → M3-eligible. FAIL → path dies. NULL → park.
- **Materiality:** Spearman(qwalk, slip) minus path baseline; deterministic floor recipe. Unmatched = missing.
- **Data manifest:** HL `asset_ctxs` published impact prices; HL fills Parquet v1.
- **Development period:** 2025-05-25 .. 2025-08-31.
- **Validation period:** 2025-09-01 .. 2025-12-31.
- **Final test period:** 2026-01-01 .. 2026-07-31; second confirmation 2026-08-01 .. 2026-12-31.
- **Features available as of:** published quotes knowable at T. Probe returns to CTO if published notional is unstable.
- **Method:** `docs/briefs/2026-08-25-p1-impact-construct.md` v3. Only `(T, T+60s]`. Buy → impact ask; sell → impact bid. Dedup by `tid`. Fuel bands are not primary cells.
- **Baselines:** trailing-range / trailing-realized-vol.
- **Metrics:** incremental Spearman; Sep–Dec sign stability.
- **Pass/fail contract:** mechanical NULL / FAIL / PASS.
- **Result:**
- **Verdict:**
- **Limitations:** one-minute match horizon is harsh; published size must be stable or probe returns.
- **Artifacts:** brief v3; D-031.
- **Correction notes:** Chair approved for banking once immediate-next-bucket and bid/ask mapping were in the brief. 2026-08-25: `1b249da` accidentally copied EXP-002 Result/Verdict into this stub. Restored blank. EXP-003 stays PLANNED; implementation deferred until after M0/M1 review. Cannot revive fuel, authorize M4, or inherit an interaction claim.


## EXP-004 — M0/M1 baseline ladder (eval-unit inventory)

- **Status:** PLANNED (P5 freeze 2026-08-25; D-032; no fitting, no scoring)
- **Frozen question:** Under the frozen evaluation unit, do price-only (M0) and generic leverage/flow (M1) baselines change OOS first-passage hazard on the primary cells?
- **Hypothesis:** Trailing path/vol/range and taker-flow variance compression are the comparison objects any later fuel/impact EXP must beat. They are not the thesis.
- **Belief change:** Banked M0/M1 become the comparison contract for later EXPs. They do not revive EXP-002 or authorize M2/M4.
- **Materiality:** family incremental Spearman on the D-032 primary cells; twin required for any PASS headline (D-026). Exact P6 floor is not locked here.
- **Data manifest:** D-022 index; `reports/exp000/index_clusters.json`; Binance kline taker fields if M1 is unblocked. No HL-fills predictive features.
- **Development period:** D-023 development 2020-01-01 .. 2023-12-31.
- **Validation period:** D-023 validation 2024-01-01 .. 2024-12-31.
- **Final test period:** D-023 final test 2025-01-01 .. 2026-07-31 as two contiguous OOS periods.
- **Features available as of:** cluster.start (catalogue already D-017 interval-end).
- **Method:** `docs/briefs/2026-08-25-p5-eval-unit.md`. P5 may only regenerate deterministic `challenger_history` from `index_clusters.json`. Scoring is P6, not this EXP's current beat.
- **Baselines:** M0 trailing 4h return / 4h range / 24h realized vol; M1 taker-flow variance compression (D-009) if as-of history exists.
- **Metrics:** four-cell family Spearman on `{1h,4h}×{up,down}`; vol-twin reported alongside.
- **Pass/fail contract:** mechanical NULL / FAIL / PASS under D-032; no score in P5.
- **Result:**
- **Verdict:**
- **Limitations:** no surviving fuel measure; M1 may block if taker as-of history is incomplete; 2024 val is thin (D-023).
- **Artifacts:** D-032; P5 brief.
- **Correction notes:** created as the Chair-authorized P5 stub only. Not a commission to fit or score.

## Experiment template

```text
## EXP-NNN — Title

- Status:
- Frozen question:
- Hypothesis:
- Data manifest:
- Development period:
- Validation period:
- Final test period:
- Features available as of:
- Method:
- Baselines:
- Metrics:
- Pass/fail contract:
- Result:
- Verdict:
- Limitations:
- Artifacts:
- Correction notes:
```

