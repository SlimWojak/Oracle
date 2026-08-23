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

- **Status:** RUNNING (data acquisition started 2026-08-23; free Binance Vision
  dumps only, no requester-pays spend)
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

