# EXP-000 event catalogue

## Parameters
- threshold: 0.02
- horizons_bars: 60, 240
- step_seconds: 60
- decision_clock: 60s
- kline_open_time: interval_start
- anchor_timestamp: interval_end
- spot_subdir: raw/binance_vision/spot/monthly/klines/BTCUSDT/1m

## Coverage
- total bars: 3459435
- range: 2020-01-01T00:00:00Z to 2026-07-31T23:59:00Z
- segments: 16
- gaps: 15 (2325.0 missing minutes)
- largest gaps:
  - 2020-02-19T11:35:00Z to 2020-02-19T17:30:00Z (354.0 missing minutes)
  - 2021-04-25T04:00:00Z to 2021-04-25T08:45:00Z (284.0 missing minutes)
  - 2021-08-13T01:59:00Z to 2021-08-13T06:30:00Z (270.0 missing minutes)
  - 2020-12-21T14:09:00Z to 2020-12-21T18:00:00Z (230.0 missing minutes)
  - 2020-06-28T01:59:00Z to 2020-06-28T05:30:00Z (210.0 missing minutes)
  - 2020-04-25T01:59:00Z to 2020-04-25T04:30:00Z (150.0 missing minutes)
  - 2021-04-20T01:59:00Z to 2021-04-20T04:30:00Z (150.0 missing minutes)
  - 2020-03-04T09:21:00Z to 2020-03-04T11:30:00Z (128.0 missing minutes)
  - 2021-09-29T06:59:00Z to 2021-09-29T09:00:00Z (120.0 missing minutes)
  - 2021-03-06T01:59:00Z to 2021-03-06T03:30:00Z (90.0 missing minutes)

## Horizon 60 bars (60 minutes)

### Labels
- total anchors: 3459435
- up: 63551
- down: 73401
- positive: 136952
- ambiguous: 16
- insufficient_horizon: 960
- none: 3321507
- positive rate: 0.039588

### Clusters
- total: 1679
- up: 560
- down: 568
- mixed: 551
- duration minutes (median/p90/max): 83.00 / 435.00 / 13269.00
- anchors per cluster (median/p90/max): 42.00 / 140.00 / 6088.00
- per-year cluster counts:
  - 2020: 282
  - 2021: 440
  - 2022: 304
  - 2023: 174
  - 2024: 237
  - 2025: 144
  - 2026: 98

## Horizon 240 bars (240 minutes)

### Labels
- total anchors: 3459435
- up: 313092
- down: 342791
- positive: 655883
- ambiguous: 19
- insufficient_horizon: 3840
- none: 2799693
- positive rate: 0.189593

### Clusters
- total: 1940
- up: 588
- down: 538
- mixed: 814
- duration minutes (median/p90/max): 368.50 / 1089.60 / 31790.00
- anchors per cluster (median/p90/max): 197.00 / 604.10 / 26459.00
- per-year cluster counts:
  - 2020: 308
  - 2021: 342
  - 2022: 332
  - 2023: 241
  - 2024: 318
  - 2025: 231
  - 2026: 168
