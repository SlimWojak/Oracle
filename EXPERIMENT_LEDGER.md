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

- **Status:** RUNNING (data acquisition started 2026-08-23)
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

