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

- **Status:** PLANNED
- **Frozen question:** Can a causal pre-state liquidation topology at time t be
  honestly reconstructed from available Hyperliquid data, given that
  cross-margin liquidation prices depend on account value, other positions,
  funding, and margin state rather than the wallet's fills alone?
- **Method sketch:** Select known cascade windows (including 2025-10-10 hour
  21). Attempt account-state reconstruction from the fill tape (positions from
  cumulative fills; margin state unobserved). For accounts subsequently
  liquidated, compare implied liquidation prices against observed
  liquidation-fill `markPx`. Determine what additional data (replica_cmds L1
  transactions, asset_ctxs funding/mark series) would be required and at what
  cost.
- **Pass condition:** Bounded, documented reconstruction error on held-out
  cascade windows sufficient to justify calling the surface "observed".
- **Failure meaning:** Per D-018 the HL challenger is demoted from observed
  fuel to realized-mass diagnostics and construct-validation evidence for the
  other challengers. The fill tape retains value either way.
- **Result:** —

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

