# EXP-000 per-fuel-challenger usable history

Source inventory: `reports/exp000/index_clusters.json` (D-022 consolidated BTC spot index).

Membership rule: cluster start_timestamp >= window start (straddlers excluded). Window starts are raw
acquisition starts; effective starts move later once feature lookbacks
are frozen. Head-to-head and incremental-lift comparisons run only on
common intersections per D-016.

## Windows

- **Price-only controls (M0)** — from 2020-01-01. D-022 consolidated BTC spot index 1m bars; context baseline, never a comparable score (D-016).
- **CEX-inferred challenger (M1+, Binance UM metrics)** — from 2021-12-01. OI/taker metrics dumps begin 2021-12; funding alone reaches back to 2020-01.
- **HL impact-context challenger (asset_ctxs)** — from 2023-05-20. Per-minute quoted impact prices, OI, premium.
- **HL fill tape (no predictive ladder this cycle, D-020)** — from 2025-05-25. Construct validation and EXP-001 only; observed-fuel status gated by D-018.

- **Vendor/model challenger** — Vendor/model challenger: no as-of point-in-time history acquired or verified; no usable window. Reconstructing history from a current vendor view is prohibited (DATA_CONTRACT).

## Horizon 60 bars

| Challenger window | from | clusters | up | down | mixed | per-year |
|---|---|---|---|---|---|---|
| Price-only controls (M0) | 2020-01-01 | 1658 | 558 | 558 | 542 | 2020: 278, 2021: 431, 2022: 301, 2023: 172, 2024: 235, 2025: 143, 2026: 98 |
| CEX-inferred challenger (M1+, Binance UM metrics) | 2021-12-01 | 983 | 342 | 358 | 283 | 2021: 34, 2022: 301, 2023: 172, 2024: 235, 2025: 143, 2026: 98 |
| HL impact-context challenger (asset_ctxs) | 2023-05-20 | 556 | 203 | 200 | 153 | 2023: 80, 2024: 235, 2025: 143, 2026: 98 |
| HL fill tape (no predictive ladder this cycle, D-020) | 2025-05-25 | 164 | 62 | 67 | 35 | 2025: 66, 2026: 98 |

## Horizon 240 bars

| Challenger window | from | clusters | up | down | mixed | per-year |
|---|---|---|---|---|---|---|
| Price-only controls (M0) | 2020-01-01 | 1935 | 594 | 534 | 807 | 2020: 317, 2021: 344, 2022: 335, 2023: 239, 2024: 309, 2025: 228, 2026: 163 |
| CEX-inferred challenger (M1+, Binance UM metrics) | 2021-12-01 | 1313 | 396 | 397 | 520 | 2021: 39, 2022: 335, 2023: 239, 2024: 309, 2025: 228, 2026: 163 |
| HL impact-context challenger (asset_ctxs) | 2023-05-20 | 820 | 258 | 257 | 305 | 2023: 120, 2024: 309, 2025: 228, 2026: 163 |
| HL fill tape (no predictive ladder this cycle, D-020) | 2025-05-25 | 287 | 99 | 98 | 90 | 2025: 124, 2026: 163 |
