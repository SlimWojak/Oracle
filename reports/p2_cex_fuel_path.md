# P2 CEX fuel path hook

P2 adds library code only for the frozen `cex_oi_cohort_v0` measurement path.
It does not run P3, compute F, or materialize a full derived table.

## Library entry points

- `oracle_research.cex_fuel.load_metrics_dir(...)` loads Binance Vision UM
  `BTCUSDT` 5-minute metrics. `create_time` is retained as interval end.
- `join_metrics_to_kline_start_grid(...)` is the explicit audit helper for
  Binance kline interval-start joins; it asserts the required
  `create_time - 5 minutes` realignment.
- `run_cex_oi_cohort_v0(...)` runs the frozen quantity-cohort state machine.
  Opening stock is unallocated and never contributes to fuel bands.
- `build_cluster_fuel_rows(...)` reduces EXP-000 4h pure-direction clusters to
  one earliest far-edge-eligible row per primary band.
- `hl_target_for_cluster_row(...)` computes the unscored Hyperliquid target hook
  for one cluster row, splitting book-hitting (`market`) and `backstop` USD.

## Minimal usage sketch

```python
from pathlib import Path

from oracle_research.cex_fuel import (
    bars_from_kline_arrays,
    build_cluster_fuel_rows,
    hl_target_for_cluster_row,
    load_cluster_payload,
    load_metrics_dir,
    metrics_rows_from_arrays,
    run_cex_oi_cohort_v0,
)
from oracle_research.hl_fills_parquet import all_fills_root

data_root = Path("/path/to/oracle-data")

# Build/load the D-022 consolidated index separately, then convert 1m
# interval-start bars to D-017 decision timestamps.
bars = bars_from_kline_arrays(index_ts, index_high, index_low, index_close)
price_by_t = {bar.timestamp: bar.close for bar in bars}

metrics = load_metrics_dir(
    data_root / "raw/binance_vision/futures/um/daily/metrics/BTCUSDT"
)
snapshots = run_cex_oi_cohort_v0(metrics_rows_from_arrays(metrics), price_by_t)

clusters = load_cluster_payload(Path("reports/exp000/index_clusters.json"))
rows = build_cluster_fuel_rows(clusters, bars, snapshots)

target = hl_target_for_cluster_row(
    rows[0],
    table_root=all_fills_root(data_root),
)
```

The target hook streams the D-012 Parquet table per `source_path` and orders only
within each source by `source_row_number`; it does not compact Parquet parts or
globally sort the fill tape.

The named trailing-path baseline attached to cluster rows is
`trailing_price_path_4h`: for downside rows it is
`max(close[T-4h:T]) / P_T - 1`; for upside rows it is
`P_T / min(close[T-4h:T]) - 1`. The current decision close is included and no
future bars are read.
