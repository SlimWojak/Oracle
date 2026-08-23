# EXP-000 per-fuel-challenger usable history

Membership rule: cluster start_timestamp >= window start (straddlers excluded). Window starts are raw
acquisition starts; effective starts move later once feature lookbacks
are frozen. Head-to-head and incremental-lift comparisons run only on
common intersections per D-016.

## Windows

- **Price-only controls (M0)** — from 2020-01-01. Binance spot 1m klines; context baseline, never a comparable score (D-016).
- **CEX-inferred challenger (M1+, Binance UM metrics)** — from 2021-12-01. OI/taker metrics dumps begin 2021-12; funding alone reaches back to 2020-01.
- **HL impact-context challenger (asset_ctxs)** — from 2023-05-20. Per-minute quoted impact prices, OI, premium.
- **HL fill tape (no predictive ladder this cycle, D-020)** — from 2025-05-25. Construct validation and EXP-001 only; observed-fuel status gated by D-018.

- **Vendor/model challenger** — Vendor/model challenger: no as-of point-in-time history acquired or verified; no usable window. Reconstructing history from a current vendor view is prohibited (DATA_CONTRACT).

## Horizon 60 bars

| Challenger window | from | clusters | up | down | mixed | per-year |
|---|---|---|---|---|---|---|
| Price-only controls (M0) | 2020-01-01 | 1679 | 560 | 568 | 551 | 2020: 282, 2021: 440, 2022: 304, 2023: 174, 2024: 237, 2025: 144, 2026: 98 |
| CEX-inferred challenger (M1+, Binance UM metrics) | 2021-12-01 | 991 | 343 | 361 | 287 | 2021: 34, 2022: 304, 2023: 174, 2024: 237, 2025: 144, 2026: 98 |
| HL impact-context challenger (asset_ctxs) | 2023-05-20 | 561 | 204 | 201 | 156 | 2023: 82, 2024: 237, 2025: 144, 2026: 98 |
| HL fill tape (no predictive ladder this cycle, D-020) | 2025-05-25 | 163 | 62 | 66 | 35 | 2025: 65, 2026: 98 |

## Horizon 240 bars

| Challenger window | from | clusters | up | down | mixed | per-year |
|---|---|---|---|---|---|---|
| Price-only controls (M0) | 2020-01-01 | 1940 | 588 | 538 | 814 | 2020: 308, 2021: 342, 2022: 332, 2023: 241, 2024: 318, 2025: 231, 2026: 168 |
| CEX-inferred challenger (M1+, Binance UM metrics) | 2021-12-01 | 1329 | 406 | 398 | 525 | 2021: 39, 2022: 332, 2023: 241, 2024: 318, 2025: 231, 2026: 168 |
| HL impact-context challenger (asset_ctxs) | 2023-05-20 | 835 | 268 | 261 | 306 | 2023: 118, 2024: 318, 2025: 231, 2026: 168 |
| HL fill tape (no predictive ladder this cycle, D-020) | 2025-05-25 | 292 | 103 | 98 | 91 | 2025: 124, 2026: 168 |
