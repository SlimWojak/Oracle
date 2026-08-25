# EXP-004 M1 source-availability audit

Overall M1 status: **BLOCKED_ASOF**.

source-only; no D-022, labels, clusters, outcomes, fits, effects, or scores.

## Manifest

- Identifier: `manifests/binance_vision_fetch.jsonl`
- SHA-256: `14c35b3b7df6af6da75ab017abdfb6fad87240358697f6192e3b71086ec1297b`
- Bytes: 697393
- Retrieval range: 2026-08-23T04:00:44.158480+00:00 .. 2026-08-23T04:05:27.355891+00:00
- Exact expected identity set: True

## Publication evidence

| Family | Status |
|---|---|
| funding | BLOCKED_ASOF_NO_PUBLICATION_TIME |
| open_interest | BLOCKED_ASOF_NO_PUBLICATION_TIME |
| perpetual_premium | CLEARED_INTERVAL_END |
| taker_flow_variance_compression | CLEARED_INTERVAL_END |

## Source audit

| Source | Archives | Rows | First timestamp | Last timestamp | Gaps | Duplicate rows | Conflicts | Off-grid |
|---|---:|---:|---|---|---:|---:|---:|---:|
| funding | 79 | 7212 | 2020-01-01T00:00:00Z | 2026-07-31T16:00:00Z | 0 | 0 | 0 | 3224 |
| metrics | 1725 | 496657 | 2021-12-01T00:00:00Z | 2026-08-21T23:55:00Z | 153 | 2 | 2 | 143 |
| spot_klines_1m | 79 | 3459435 | 2020-01-01T00:00:00Z | 2026-07-31T23:59:00Z | 15 | 0 | 0 | 0 |
| um_klines_1m | 79 | 3461760 | 2020-01-01T00:00:00Z | 2026-07-31T23:59:00Z | 0 | 0 | 0 | 0 |

## Source-only hourly availability

| Period | Family | Available / candidate | Coverage | Floor pass |
|---|---|---:|---:|---|
| M1_DEV | funding | 18263 / 18263 | 1.000000 | True |
| M1_DEV | open_interest | 18250 / 18263 | 0.999288 | True |
| M1_DEV | perpetual_premium | 18261 / 18263 | 0.999890 | True |
| M1_DEV | taker_flow_variance_compression | 18221 / 18263 | 0.997700 | True |
| M1_DEV | **four-family joint** | 18206 / 18263 | 0.996879 | True |
| VALIDATION | funding | 8784 / 8784 | 1.000000 | True |
| VALIDATION | open_interest | 8739 / 8784 | 0.994877 | True |
| VALIDATION | perpetual_premium | 8784 / 8784 | 1.000000 | True |
| VALIDATION | taker_flow_variance_compression | 8769 / 8784 | 0.998292 | True |
| VALIDATION | **four-family joint** | 8724 / 8784 | 0.993169 | True |
| TEST_2025 | funding | 8760 / 8760 | 1.000000 | True |
| TEST_2025 | open_interest | 8757 / 8760 | 0.999658 | True |
| TEST_2025 | perpetual_premium | 8760 / 8760 | 1.000000 | True |
| TEST_2025 | taker_flow_variance_compression | 8740 / 8760 | 0.997717 | True |
| TEST_2025 | **four-family joint** | 8737 / 8760 | 0.997374 | True |
| TEST_2026 | funding | 5088 / 5088 | 1.000000 | True |
| TEST_2026 | open_interest | 5088 / 5088 | 1.000000 | True |
| TEST_2026 | perpetual_premium | 5088 / 5088 | 1.000000 | True |
| TEST_2026 | taker_flow_variance_compression | 5088 / 5088 | 1.000000 | True |
| TEST_2026 | **four-family joint** | 5088 / 5088 | 1.000000 | True |

Coverage clearance: True

Zero-joint full calendar months: none

Coverage cannot override the publication-evidence gate.

## Frozen candidate transformations

### open_interest

- Source: Binance USD-M BTCUSDT five-minute metrics
- Field/unit: sum_open_interest_value, USDT quote notional
- Timestamp: raw create_time; candidate interval end; off-grid rows unusable
- As-of: exact raw row at T-5m
- Transform: `oi_level_T = log(sum_open_interest_value[T-5m])`
- Missingness: missing, conflicted, off-grid, nonfinite, or nonpositive row => missing
- Effective raw start: 2021-12-01
- Publication evidence: BLOCKED_ASOF_NO_PUBLICATION_TIME

### funding

- Source: Binance USD-M BTCUSDT monthly funding history
- Field/unit: last_funding_rate, dimensionless realized settlement rate
- Timestamp: raw millisecond calc_time event stamp; never rounded or floored
- As-of: exactly three rows in (T-24h-5m, T-5m], each interval=8h
- Transform: `funding_24h_T = sum(last_funding_rate)`
- Missingness: not exactly three unique finite 8h settlements => missing
- Effective raw start: 2020-01
- Publication evidence: BLOCKED_ASOF_NO_PUBLICATION_TIME

### perpetual_premium

- Source: Binance USD-M and spot BTCUSDT one-minute klines
- Field/unit: perpetual and spot close, USDT per BTC
- Timestamp: open_time interval start; decision-time interval end = open_time+60s
- As-of: both exact one-minute bars ending at T
- Transform: `premium_T = log(perp_close_T / spot_close_T)`
- Missingness: either exact bar missing/conflicted/nonfinite/nonpositive => missing
- Effective raw start: 2020-01
- Publication evidence: CLEARED_INTERVAL_END

### taker_flow_variance_compression

- Source: Binance USD-M BTCUSDT one-minute kline quote-volume fields
- Field/unit: quote_volume and taker_buy_quote_volume, USDT
- Timestamp: five complete 1m bars per UTC-aligned block; newest block ends T-5m
- As-of: 96 complete q points per 8h residual and 24 complete residuals per 2h variance
- Transform: `q=log(B/(Q-B)); 8h mean residual; -log(population variance over 2h)`
- Missingness: any absent/nonfinite input, B<=0, S<=0, or variance<=0 => missing
- Effective raw start: 2020-01 plus frozen lookbacks
- Publication evidence: CLEARED_INTERVAL_END
