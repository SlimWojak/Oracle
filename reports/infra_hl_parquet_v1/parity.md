# HL Parquet v1 parity gate

- Status: **PASS**
- Parquet table: `/home/a8ra_dgx/oracle-data/derived/hyperliquid/fills/v1/all_fills`
- Expected census: `reports/exp001/stratification_census.json`

| Check | Actual | Expected | Pass |
|---|---:|---:|---|
| `total_btc_liquidation_events` | 1462734 | 1462734 | yes |
| `total_btc_liquidation_notional_usd` | 23093649899.03648 | 23093649899.03648 | yes |
| `tractable_share` | 0.3906399647411886 | 0.3906399647411886 | yes |
| `counts_by_stratum.a_btc_only_isolated` | 828 | 828 | yes |
| `counts_by_stratum.b_btc_only_cross` | 802516 | 802516 | yes |
| `counts_by_stratum.c_cross_asset` | 659390 | 659390 | yes |
| `notional_usd_by_stratum.a_btc_only_isolated` | 19822574.872812986 | 19822574.872812986 | yes |
| `notional_usd_by_stratum.b_btc_only_cross` | 9001480007.432152 | 9001480007.432152 | yes |
| `notional_usd_by_stratum.c_cross_asset` | 14072347316.731516 | 14072347316.731516 | yes |
| `counts_by_method.backstop` | 4715 | 4715 | yes |
| `counts_by_method.market` | 1458019 | 1458019 | yes |
| `notional_usd_by_method.backstop` | 1315033878.1347132 | 1315033878.1347132 | yes |
| `notional_usd_by_method.market` | 21778616020.901707 | 21778616020.901707 | yes |
