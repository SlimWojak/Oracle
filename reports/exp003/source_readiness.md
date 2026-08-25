# EXP-003 Checkpoint A source readiness

**Mechanical status: `BLOCKED_SOURCE` (pre-effect).**

No eligibility census, VWAP, qwalk, slippage, correlation, bootstrap, or
one-shot execution was run. The source gate failed first, so the v4 contract
requires a stop without scoring.

## Blocking conditions

1. **The historical impact notional is multi-regime and unversioned.** The raw
   `asset_ctxs` CSV has `impact_bid_px` and `impact_ask_px`, but no impact
   notional or source-semantics version. Hyperliquid's official contract page
   documents 20,000 USDC for BTC/ETH, and 17 available official-page captures
   from 2024-03-24 through 2026-05-20 agree. Source-only L2 walks nevertheless
   reproduce approximately 5,000 USDC from 2023-05-20 through 2023-05-30 and
   20,000 USDC after a change in `(2023-05-31T01:32:00Z,
   2023-05-31T01:32:22Z]`. No authoritative versioned specification was found
   for the early regime.
2. **As-of/publication semantics are unproven.** Raw `time` behaves like a
   point-snapshot stamp, including off-grid seconds. The archive supplies no
   receive time, publication time, block number, or sequence. The official
   archive page says files are uploaded approximately monthly and may be
   missing, but does not define when a CSV row stamped `T` became publicly
   knowable. The live asset-context type also carries no timestamp.

Either condition independently fails Checkpoint A. Restricting the probe to the
later 20,000-USDC regime would change the frozen history rule and is not an
allowed rescue.

## Raw schema and coverage

All 1,168 files found across 2023-05-20..2026-07-31 share one 12-column header:

```text
time,coin,funding,open_interest,prev_day_px,day_ntl_vlm,premium,oracle_px,mark_px,mid_px,impact_bid_px,impact_ask_px
```

- Expected files: 1,169; missing: `20260708.csv.lz4`.
- Rows streamed: 259,948,917 all-asset; 1,658,847 BTC.
- BTC span: 2023-05-20T02:50:04Z..2026-07-31T23:59:00Z.
- Exact-minute rows: 1,657,605; off-grid rows: 1,242.
- Exact raw duplicate/conflicting timestamps: 0 / 0.
- Flooring would create 161 collisions (144 with different quote/mark triples),
  all before fills begin. P4 therefore cannot floor timestamps.
- Null, malformed, non-finite, out-of-order, wrong-width, and filename/date
  conflict counts are all zero.
- There are 147 nonpositive key-price rows, all in descriptive pre-fill history.

| Period | Exact minutes | Expected | Coverage | Missing | Max gap |
|---|---:|---:|---:|---:|---:|
| pre-fills descriptive | 1,036,782 | 1,059,669 | 97.8402% | 22,887 | 594m |
| construct-dev | 142,374 | 142,560 | 99.8695% | 186 | 31m |
| construct-val | 175,662 | 175,680 | 99.9898% | 18 | 2m |
| first look | 302,787 | 305,280 | 99.1834% | 2,493 | 1,440m |

## Effect-blind L2 notional corroboration

For the nearest official BTC L2 `raw.data.time`, each candidate book walk
consumed `min(remaining_USDC, px*sz)` and compared bid/ask VWAP with the
archived impact prices. The error below is summed absolute bid/ask price error
divided by their mean, in basis points.

| Asset-context time | L2 lag | 5k error | 10k error | 20k error | Winner |
|---|---:|---:|---:|---:|---:|
| 2023-05-20 12:00Z | +48ms | 0.283 | 2.797 | 13.702 | 5k |
| 2024-01-01 12:33Z | -210ms | 0.0676 | 0.0221 | 0.0007 | 20k |
| 2026-07-31 12:26Z | -1,862ms | 0.5023 | 0.2586 | 0.0119 | 20k |

Every daily-noon sample from May 20 through May 30 selected 5k (11/11), as did
all 24 hourly samples on May 30. Transition samples:

| Time | 5k error | 20k error | Winner |
|---|---:|---:|---:|
| 2023-05-31 01:32:00Z | 0.27 | 4.85 | 5k |
| 2023-05-31 01:32:22Z | 4.12 | 0.03 | 20k |
| 2023-05-31 01:33:00Z | 5.03 | 0.05 | 20k |

This is strong source-only corroboration, not a substitute for a versioned
venue specification: the asset-context and L2 clocks are not transactionally
synchronized.

## Authoritative source trail

- [Hyperliquid funding specification](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding)
- [Hyperliquid contract specifications](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/contract-specifications)
- [Earliest available contract-page capture checked (2024-03-24)](https://web.archive.org/web/20240324125006id_/https://hyperliquid.gitbook.io/hyperliquid-docs/trading/contract-specifications)
- [Hyperliquid historical-data documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data)
- [Pinned official SDK asset-context type](https://github.com/hyperliquid-dex/hyperliquid-python-sdk/blob/2fdb18f9517675ea03695a0962bd19eece9c83f0/hyperliquid/utils/types.py#L99-L112)

## Stop

`EXP-003 = BLOCKED`. The exact next-60-second eligibility census is
`NOT_RUN_SOURCE_BLOCK`; the quoted-impact scorer and one-shot receipt do not
exist. No proxy, alternate history, notional, window, or later candidate is
substituted.
