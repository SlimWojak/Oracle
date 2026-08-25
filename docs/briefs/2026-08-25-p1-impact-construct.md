# P1 — EXP-003 impact construct (draft v3)

CTO draft 2026-08-25, v3. **Chair approved for banking (D-031).**
Designed now; implemented only after EXP-002 has a recorded verdict.
Engineer may inspect `asset_ctxs` schema; Engineer may **not** select
the matching design. If the published impact notional is not a single
stable USD figure across the usable window, the probe **returns to CTO**
and does not score.

## Claim (narrow)

First impact proxy: **visible / quoted book-walk susceptibility** on
Hyperliquid, using the venue’s published impact prices from `asset_ctxs`.

A PASS makes this proxy eligible for M3. A FAIL kills this path. A NULL
parks. Trailing realized impact is a later independent candidate and is
not blended.

## Order-size rule (frozen)

Use the venue-published impact-quote notional. P4 schema probe records
field names and that USD notional **before** any score, then stops for
CTO if missing, multi-valued, or unstable across 2023-05-20 onward.

## Realized-match unit (frozen)

One unit is `(decision_timestamp T, side s)`.

- Unique **taker / crossed** BTC fills, **deduplicated by `tid`**.
- **Only the immediately following epoch-aligned 60-second bucket,
  `(T, T+60s]`.** If its same-side notional is outside `[0.5×, 2.0×]`
  the published impact notional, the unit is unmatched. **Do not search
  forward** for a later eligible bucket.
- Quote at T; flow strictly after T (fills with time_ms > T only).
- Unmatched windows are **missing, never zero**.
- Backstop and ADL excluded.

## Side mapping (explicit)

- Aggressive buy / taker-buy: published **impact ask**; `side = +1`.
- Aggressive sell / taker-sell: published **impact bid**; `side = −1`.

```
qwalk = side * (impact_px_side / decision_px − 1)
slip  = side * (VWAP_bucket    / decision_px − 1)
```

`decision_px` is HL `mark_px` from `asset_ctxs` at T.
`VWAP_bucket` is size-weighted `px` of deduped crossed fills in
`(T, T+60s]` on that side.

## Observation unit

`(T, side)`. Horizons are not a family axis. **Fuel distance bands are
not EXP-003 primary cells.** Decision clock: 1-minute interval-end.
Clustering: EXP-000 clusters + UTC-week blocks. Mixed clusters do not
count toward side-specific coverage.

## Firewall (D-029, Chair-approved)

Fill-matched scoring:

- construct-dev 2025-05-25 .. 2025-08-31;
- construct-val 2025-09-01 .. 2025-12-31;
- first look 2026-01-01 .. 2026-07-31;
- second confirmation 2026-08-01 .. 2026-12-31.

Quoted-impact history from 2023-05-20 is descriptive only.

## Materiality

Primary statistic: Spearman(`qwalk`, `slip`) minus the same for a
trailing-range / trailing-realized-vol baseline.

Floor lock: `numpy.random.default_rng(20250825)`, UTC-week block
resample with replacement, B=1000, `SE` with ddof=1,
`floor = max(0.10, 2*SE)`, coverage ≥ 30 pure-direction clusters per
side. Constant-input Spearman → NULL. NULL if no floor or coverage
fail; FAIL if powered and below floor / CI covers 0 / no incremental
value / sign unstable across Sep–Dec 2025.

## Anti-goals

- Searching past the next 60s bucket.
- P4 discretion over match window, size band, or formula.
- Blending quoted walk with trailing realized impact.
- Fuel bands in the primary cell.
- Double-counting both fill legs.
