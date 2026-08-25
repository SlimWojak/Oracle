# P4 — EXP-003 quoted book-walk construct (implementation freeze v4)

CTO freeze 2026-08-25. v3 was approved in D-031; this v4 closes the
implementation ambiguities under the later P4 commission. No correlation or
realized-slippage effect may be inspected until the source and eligibility gates
below are banked. A source or coverage stop is a disposition, not a redesign
license.

## Claim (narrow)

First impact proxy: **visible / quoted book-walk susceptibility** on
Hyperliquid, using the venue's published BTC impact prices from `asset_ctxs`.

A PASS makes this proxy eligible for M3. A FAIL kills this path. A NULL parks
it. Trailing realized impact is a later independent candidate and is not
blended. EXP-003 cannot revive fuel, authorize M1/M2/M3/M4, or inherit an
interaction claim.

## Checkpoint A — source gate

The effect-blind readiness report must verify all of the following across the
available `asset_ctxs` history from 2023-05-20 through 2026-07-31, with the
fill-matched periods called out separately:

- BTC fields are exactly `time`, `coin`, `mark_px`, `impact_bid_px`, and
  `impact_ask_px`; schema aliases are not accepted by the canonical P4 path.
- `time` is the UTC source/observation timestamp of an instantaneous context
  snapshot. It is neither an interval-start nor an interval-end bar stamp.
  The quote is used only at that exact timestamp; no flooring, stale lookup,
  forward fill, or later archive-publication time is used as market time.
- The archive exposes no receive timestamp. Retrieval/publication metadata is
  retained in provenance and never substituted for source time.
- `mark_px` is the decision price. `impact_bid_px` is the average execution
  price for a sell into bids and `impact_ask_px` for a buy into asks.
- The one authoritative BTC funding-impact notional is **20,000 USDC**. The
  source report must cite the venue's own contract specification and historical
  official-page captures, and must find no contrary field, version, or
  source-only reproduction across the usable history.

Missing, multi-valued, historically unstable, or causally indefensible notional
or timestamp semantics produce `BLOCKED_SOURCE` before scoring. Empirical
agreement alone cannot replace authoritative venue evidence.

## Order-size rule (frozen)

`impact_notional_usdc = 20_000`. A side bucket is size-eligible when its
deduped same-side fill notional is in the inclusive band
`[10_000, 40_000]` USDC (`[0.5x, 2.0x]`). Notional is `px * sz` in the
venue's linear BTC-perpetual quote convention. No other size, normalization,
proxy, or parameter sweep exists in EXP-003.

## Decision rows and quote conflicts

One candidate decision row is an exact BTC context timestamp `T` on the UTC
minute grid. Duplicate rows with identical canonical values collapse to one.
If rows at `(T, BTC)` disagree on any canonical quote field, both sides at `T`
are missing with reason `QUOTE_CONFLICT`. Non-finite/non-positive prices or
`impact_bid_px > impact_ask_px` are invalid and missing. A missing exact row is
`QUOTE_MISSING`; it is never filled from a neighboring minute.

## Crossed-fill selection and deduplication

The fill event time is `time_ms`. `block_time` and `local_time`, where present,
are retained as source/receive diagnostics but never replace `time_ms` for the
match.

For the union of the old and by-block fill stores:

1. Project BTC rows with `crossed == true`; this is the taker leg.
2. Side `B` is aggressive buy (`side = +1`); side `A` is aggressive sell
   (`side = -1`). Unknown sides are invalid.
3. Exclude `liquidation_method == "backstop"` and
   `dir == "Auto-Deleveraging"`. Ordinary crossed fills and book-hitting
   `liquidation_method == "market"` fills remain eligible.
4. Deduplicate globally by bare `tid`. Repeated rows with identical economic
   and classification values `(coin, time_ms, side, px, sz, crossed, dir,
   liquidation_method)` collapse to one. If crossed rows sharing a `tid`
   conflict on any of those values, exclude the entire `tid` as
   `TID_CONFLICT`; first-file/last-file wins are forbidden.
5. Require finite positive `px` and `sz`.

## Realized-match unit (frozen)

One unit is `(decision_timestamp T, side s)`.

- Quote at exact `T`; flow only in the immediately following epoch-aligned
  bucket **`(T, T+60_000ms]`**.
- A fill at `T` is excluded. A fill at `T+60_000ms` is included. No fill after
  that endpoint can rescue the unit.
- Aggregate all valid deduped same-side fills in the bucket. If total notional
  is outside `[10_000, 40_000]`, the unit is unmatched/missing, never zero.
- The VWAP numerator and denominator use the same deduped rows. No truncation
  to 20,000 USDC is performed.

Side mapping and measures:

```text
aggressive buy:  side = +1, quote = impact_ask_px
aggressive sell: side = -1, quote = impact_bid_px

qwalk = side * (quote / mark_px - 1)
slip  = side * (VWAP_bucket / mark_px - 1)
```

## One causal baseline (frozen)

The only baseline is normalized trailing range from the same exact BTC
`asset_ctxs.mark_px` series. Let `P_u` be the exact mark at minute `u`:

```text
range_4h(T) = log(max(P_u) / min(P_u)) for u in (T-4h, T]
rv_24h(T)   = sqrt(sum(log(P_u / P_{u-60s})^2)) for u in (T-24h, T]
baseline(T) = range_4h(T) / rv_24h(T)
```

`range_4h` requires all 240 exact minute marks. `rv_24h` requires all 1,441
marks needed for 1,440 returns and must be finite and strictly positive. No
annualization, demeaning, winsorization, imputation, alternative lookback, or
second baseline is permitted.

## Period and boundary rules

Primary periods are UTC and fixed:

- construct-dev: `[2025-05-25, 2025-09-01)`;
- construct-val: `[2025-09-01, 2026-01-01)`;
- first look: `[2026-01-01, 2026-08-01)`.

A candidate `T` belongs to a period only when its full next bucket ends no later
than the period end. Thus the last possible `T` is `period_end - 60s`. The
validation stability blocks are `[2025-09-01, 2025-11-01)` and
`[2025-11-01, 2026-01-01)` under the same full-bucket rule.

The incomplete 2026-08-01..2026-12-31 confirmation window is
`NOT_AVAILABLE` and is not read, scored, imputed, or treated as negative
evidence. An EXP-003 PASS is construct eligibility for M3 only, not a
definitive predictive PASS headline under D-029.

## Coverage and dependence (frozen before census)

Horizons are not a score-family axis. The conservative dependence and coverage
unit is the D-022 **4h event cluster**.

- Score rows are all matched `(T, side)` rows; they are not selected by future
  cluster membership.
- A pure-up 4h cluster covers the buy side and a pure-down 4h cluster covers
  the sell side. Mixed clusters never count toward either coverage floor.
- A cluster counts once when its `start_timestamp` lies in the period and at
  least one otherwise score-eligible aligned-side `T` lies inside the cluster's
  inclusive `[start_timestamp, end_timestamp]` span.
- Require at least **30 covered pure-direction clusters per side in each of
  construct-dev, construct-val, and first look**. This is the existing v3
  30-cluster floor applied to every primary scored period; periods may not be
  pooled to rescue coverage.

The readiness census reports candidate quote rows, baseline-available rows,
matched/unmatched units and reasons, size-band endpoints, and unique covered
4h clusters by period and side. It may use fill `px * sz` only to determine
size eligibility. It must not calculate VWAP, `qwalk`, `slip`, any correlation,
or any effect-conditioned selection. A coverage miss produces pre-effect
`NULL_COVERAGE` and stops the path without scoring.

## Primary statistic (one family, no menu)

For side `s` and window `W`:

```text
rho_qwalk(s,W)    = Spearman(qwalk, slip)
rho_baseline(s,W) = Spearman(baseline, slip)
delta(s,W)        = rho_qwalk(s,W) - rho_baseline(s,W)
F(W)              = (delta(buy,W) + delta(sell,W)) / 2
```

`F` is the sole primary family statistic. Side rows are never pooled. Both
side results are reported and neither direction may be rescued by the other.
Constant, non-finite, or fewer-than-two-value Spearman inputs are undefined.

## Bootstrap and floor lock

Use one `numpy.random.default_rng(20250825)` stream, `B=1000`, in this fixed
window order: construct-dev, construct-val, Sep-Oct, Nov-Dec, first look.

The resampling unit is a family-wide UTC-week block. A row inside a D-022 4h
cluster is assigned to the UTC week containing that cluster's start; every
other row is assigned to the UTC week containing `T`. Sample the window's
unique blocks with replacement, drawing the same multiplicities for both
sides and every row linked to a cluster. Compute side deltas and `F` on every
draw. Bootstrap SE is the sample standard deviation with `ddof=1`; the 95%
interval is the 2.5/97.5 percentile interval.

The development floor locks only when all 1,000 development draws define `F`:

```text
floor = max(0.10, 2 * bootstrap_SE(F_construct_dev))
```

Any undefined development draw, non-finite SE, or failure to lock the floor is
`NULL_FLOOR`; it is not permission to change the bootstrap.

## Mechanical disposition

After source, coverage, integrity, and floor gates clear, PASS requires all of:

1. In construct-val and first look separately, `F >= floor` and the bootstrap
   95% interval for `F` has lower bound strictly greater than zero.
2. In both periods, each side has `rho_qwalk > 0` and `delta > 0`.
3. `F > 0` in both Sep-Oct and Nov-Dec validation stability blocks, with all
   required side correlations defined.

The result is applied without pooled, slice, or post-hoc rescue:

- `BLOCKED`: source/as-of/notional/provenance/immutable-run integrity fails.
- `NULL`: pre-effect coverage fails, the development floor cannot lock, or a
  required statistic is undefined/constant despite valid inputs.
- `PASS`: every clause above is true.
- `FAIL`: the run is valid and powered but at least one PASS clause is false.

A result-affecting defect discovered after the one-shot run returns to Chair;
it is not silently patched and rerun.

## Anti-goals

- Searching past the next 60-second bucket.
- Changing the inclusive `[0.5x, 2x]` size band or 20,000-USDC quote size.
- Blending quoted walk with trailing realized impact.
- Fuel bands or label horizons in the primary family.
- Double-counting both fill legs or resolving conflicts by file order.
- Reading 2026-08..12, sweeping parameters, or using a slice to rescue a miss.
