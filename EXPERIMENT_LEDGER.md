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

- **Status:** PLANNED
- **Question:** Is there sufficient point-in-time data and independent +/-2% event
  coverage to test the v0 contract without pseudo-replication?
- **Inputs:** Consolidated BTC index candidate feeds and availability metadata for
  fuel, impact, and ignition sources.
- **Method:** Build fixed 1h/4h first-passage labels; identify ambiguous bars; cluster
  adjacent labels into independent events; produce source-by-time coverage matrix.
- **Required outputs:** Timestamp counts, independent cluster counts, direction and
  horizon breakdown, gap report, proposed time splits, unresolved data decisions.
- **Pass condition:** Coverage supports at least one honest development/validation/
  test design or clearly identifies a justified discovery-only alternative.
- **Failure meaning:** Revise scope or data acquisition before feature engineering.
- **Result:** Not run.

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

