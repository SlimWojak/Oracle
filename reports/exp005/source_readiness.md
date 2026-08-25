# EXP-005 Checkpoint A source readiness

**Disposition:** `CLEARED_CHECKPOINT_A`

source/support only; no labels, outcomes, clusters, fits, effects, or scores.

## Selected source manifest

- Identifier: `manifests/binance_vision_fetch.jsonl`
- Selected identities: 79 / 79
- Exact selected identity set: True
- Non-selected full-manifest records ignored: 1883

## USD-M kline and block audit

- Archives read: 79
- Rows: 3461760
- Epoch units: `{'epoch_ms': 3461760}`
- Raw close-time audit: `{'standard_offset': 3461760, 'nonstandard_offset': 0, 'before_open': 0, 'after_nominal_end': 0, 'causal': 3461760, 'unparseable': 0}`
- Duplicate handling: `{'duplicate_rows': 0, 'identical_duplicate_timestamps': 0, 'conflicting_timestamps': 0, 'handling': 'identical raw rows collapse once; differing rows are missing'}`
- Aligned 5m candidates: 692459
- Structurally valid 5m blocks: 692339
- q-valid 5m blocks: 692273
- 5m reason census: `{'MISSING_MINUTE': 120, 'NONPOSITIVE_BUY': 66, 'VALID_Q': 692273}`

## D-022 source/index and exact M0 verification

- D-022 source inputs verified: 11770 / 11770
- D-022 verified source bytes: 653828637
- Median index reconstructed: True
- Median index rows: 3461652
- 3-of-3 / 2-of-3 rows: 3405505 / 56147
- Exact M0 columns: `['trend_4h', 'range_4h', 'rv_24h', 'hour_sin', 'hour_cos', 'weekday_sin', 'weekday_cos']`
- M0 availability reasons: `{'MISSING_RANGE_BAR': 81, 'MISSING_RV': 13, 'MISSING_TREND_ENDPOINT': 2, 'VALID': 57602}`

## Source-only hourly support

| Period | Flow | Flow rate | Joint seven-M0+flow | Joint rate | Zero months |
|---|---:|---:|---:|---:|---:|
| development | 35002 / 35064 | 0.998232 | 34918 / 35064 | 0.995836 | 0 |
| validation_2024 | 8769 / 8784 | 0.998292 | 8769 / 8784 | 0.998292 | 0 |
| test_2025 | 8740 / 8760 | 0.997717 | 8740 / 8760 | 0.997717 | 0 |
| test_2026_01_07 | 5088 / 5088 | 1.000000 | 5088 / 5088 | 1.000000 | 0 |

Coverage clearance: True

Every period also records ordered candidate, flow, M0, joint paired-rung, and D-023 four-hour clock-purge support hashes in the JSON artifact.

## Causal ruling

USD-M source rows are interval bars; `open_time` is interval start and the causal end is `open_time + 60s`. Every five-minute block requires all five exact minutes. The newest block ends at `T-5m`. No partial window, epsilon, rounding, forward fill, post-T input, or alternate field is used.

D-023 boundary purge reporting is clock-only. No cluster-straddle or future window was read at Checkpoint A.
