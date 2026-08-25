# P6 implementation contract freeze — EXP-004 M0/M1

CTO 2026-08-25. This freezes an implementation contract only. It does not
authorize P6 implementation, fitting, scoring, alert-threshold estimation, or
inspection of any validation/test effect. EXP-004 remains PLANNED and unscored.
P4 / EXP-003, M2+, fuel retries, and new feature families remain outside scope.

## 1. Evaluation population inherited unchanged from D-032

The unit is one causal D-022 state at each exact UTC clock hour `T`, before the
frozen impulse:

```text
abs(log(P_T / P_{T-15m})) < log(1.005)
```

Both endpoints must be exact D-022 interval-end closes. Equality and missing
endpoints are ineligible. The linked horizons are 1h and 4h. Fixed and twin
labels use one common risk set and the D-032 categorical first cause
`{UP, DOWN, NONE}`; `AMBIGUOUS` and `CENSORED_GAP` are unscored and counted.
The opposite first passage is a competing event, not censoring. No item below
changes the D-023 split, four-hour boundary purge, cluster-straddle rule,
timestamp/episode/cluster weights, or UTC-week bootstrap.

For a horizon, a timestamp is scoreable for fixed/twin comparison only when
both label-family outcomes are in `{UP, DOWN, NONE}`. A model rung may further
lose rows only through its frozen complete-case feature mask. Every comparison
names that mask explicitly.

## 2. Exact M0

All price inputs are D-022 consolidated-index bars. No forward fill or
interpolation is permitted.

At hourly `T`, M0 is the ordered vector:

1. `trend_4h = log(P_T / P_{T-4h})`; both closes must exist exactly.
2. `range_4h = log(max(high_u) / min(low_u))` over the 240 interval-end bars
   `u in (T-4h, T]`; all 240 bars must exist and be positive and finite.
3. `rv_24h = sqrt(sum(r_u**2))`, where
   `r_u = log(P_u / P_{u-1m})` on `(T-24h, T]`; only exactly consecutive
   one-minute pairs count, at least 720 finite returns are required, and the
   result must be positive and finite. This is exactly D-032 `sigma_T`.
4. `sin(2*pi*hour_utc(T)/24)` and `cos(2*pi*hour_utc(T)/24)`.
5. With Monday equal to zero,
   `sin(2*pi*weekday_utc(T)/7)` and `cos(2*pi*weekday_utc(T)/7)`.

There are seven M0 columns. No return magnitude, month, event tag, outcome, or
post-`T` value enters M0. Calendar values are evaluated at `T` itself.

## 3. Exact M1 candidates and as-of gate

M1 is exactly M0 plus the four columns below. The complete family is required;
one surviving input cannot stand in for another. All numeric inputs must be
finite, and all price/quantity inputs used inside a logarithm must be strictly
positive. A failed rule yields a missing feature at `T`, never an imputed value
or missingness indicator.

### 3.1 Open interest

- Candidate source: Binance USD-M BTCUSDT five-minute metrics,
  `sum_open_interest_value`, in quote-notional USDT. The account-count and
  top-trader ratios are prohibited substitutes.
- Timestamp: raw `create_time`, interpreted as interval end per D-017 and the
  data contract. Off-grid timestamps are not floored. Differing duplicate raw
  timestamps are marked conflicted and unusable; later-file overwrite is not
  allowed for EXP-004.
- Candidate as-of row: the exact raw row at `T-5m`. This one-full-interval lag
  is necessary but is not by itself evidence of historical publication.
- Transform: `oi_level_T = log(sum_open_interest_value_{T-5m})`.
- Effective raw start: 2021-12-01. M1 cannot extend earlier by substitution.

An OI collapse, OI change, or liquidation-conditioned OI measure is not this
feature and may not be introduced silently.

### 3.2 Funding

- Candidate source: Binance USD-M BTCUSDT monthly funding history,
  `last_funding_rate`; it is a realized settlement rate, not a forecast.
- Timestamp: the raw millisecond `calc_time` event stamp. It is never rounded
  or floored to a nominal eight-hour boundary.
- Candidate as-of window: raw settlements in `(T-24h-5m, T-5m]`. Require
  exactly three rows, `funding_interval_hours == 8` on each, unique raw stamps,
  and finite rates.
- Transform: `funding_24h_T = sum(last_funding_rate)` over those three rows.

### 3.3 Perpetual premium

- Candidate sources: Binance USD-M BTCUSDT perpetual and Binance spot BTCUSDT
  one-minute klines. The standard 12-position kline schema is frozen even when
  a CSV header is absent. Epoch milliseconds and microseconds are normalized
  explicitly before any join.
- Timestamp: raw kline `open_time` denotes interval start; the decision-time
  interval end is `open_time + 60s` under D-017. Raw `close_time` is retained
  as an audit field. It is not silently rewritten and must not exceed the
  decision-time interval end.
- Candidate as-of pair: both exact one-minute bars ending at `T`.
- Transform: `premium_T = log(perp_close_T / spot_close_T)`.

No Hyperliquid premium and no cross-venue basis splice is permitted.

### 3.4 Taker-flow variance compression

The motivating study used a Binance five-minute taker buy/sell volume ratio and
found lower residual variance before each of its usable cascades. EXP-004 uses
the same construct from the more complete raw USD-M kline quote-volume fields,
not the nullable aggregate metrics ratio. This source choice is frozen before
any outcome effect is read.

For every UTC-aligned five-minute block ending at `s`:

```text
Q_s = sum(quote_volume) over the five exact USD-M 1m bars in (s-5m, s]
B_s = sum(taker_buy_quote_volume) over those bars
S_s = Q_s - B_s
q_s = log(B_s / S_s)
```

Require all five raw bars, finite values, and `B_s > 0`, `S_s > 0`. Then:

```text
m_s = mean(q_v for v = s-475m, s-470m, ..., s)       # 96 points / 8h
e_s = q_s - m_s
v_T = mean((e_s - mean(e))**2
           for s = T-120m, T-115m, ..., T-5m)        # 24 points / 2h
flow_compression_T = -log(v_T)
```

All 96 inputs for every residual and all 24 residuals are required; `v_T` must
be positive and finite. There is no epsilon, partial-window rule, or forward
fill. The newest block ends at `T-5m`, imposing one complete five-minute
availability lag. The 8h detrend and 2h variance windows are one pre-outcome
specification near the middle of the motivating paper's reported 2–16h and
0.5–4h grids; there is no parameter sweep in EXP-004.

### 3.5 Publication evidence is a hard gate

Source/event time does not prove publication time. A stock/event family passes
the point-in-time gate only if the banked source supplies a historical
publication/receive timestamp or an authoritative latency guarantee that makes
the frozen lag conservative. An arbitrary safety delay is not proof.

D-017 interval completion is sufficient for the two kline-derived families
because the exact same exchange-bar convention underlies Oracle's causal price
inputs. It does not automatically validate metrics snapshots or funding events.
If OI or funding lacks the required evidence, M1 is `BLOCKED_ASOF` as a complete
rung. Do not acquire a substitute, shrink M1, or proceed to a fit inside this
commission. The exact candidate transforms above remain frozen for a future
decision if point-in-time evidence is supplied.

## 4. Source-only availability audit

The D-019 audit is label-blind and effect-blind. It records archive identities
and hashes, schema, source-time semantics, normalized coverage, duplicates,
off-grid rows, gaps, field null/finite/positivity counts, effective feature
start, and hourly feature availability for these periods:

- `M1_DEV`: 2021-12-01T01:00Z through 2023-12-31T23:00Z;
- `VALIDATION`: 2024-01-01T00:00Z through 2024-12-31T23:00Z;
- `TEST_2025`: 2025-01-01T00:00Z through 2025-12-31T23:00Z;
- `TEST_2026`: 2026-01-01T00:00Z through 2026-07-31T23:00Z.

These counts use the UTC-hour source clock only, before D-022 availability,
precondition filtering, outcomes, or split-boundary drops. For a later
availability clearance, each family must cover at least 90% of candidate hours,
the four-family intersection at least 85% in every period, and no full calendar
month may have zero joint coverage. Passing these coverage floors cannot
override the publication-evidence gate.

## 5. Exact joint-probability estimator

For each rung (`M0`, `M0_COMMON`, `M1`), horizon, and label family, fit one
baseline-category multinomial logistic regression. `NONE` is the reference:

```text
eta_up   = a_up   + x @ beta_up
eta_down = a_down + x @ beta_down
D        = 1 + exp(eta_up) + exp(eta_down)
p_up     = exp(eta_up) / D
p_down   = exp(eta_down) / D
p_none   = 1 / D
```

The implementation must use a numerically stable log-sum-exp form. It minimizes
the equal-row-weight development objective

```text
mean(categorical negative log likelihood)
+ 0.5 * 1e-4 * (||beta_up||**2 + ||beta_down||**2)
```

Intercepts are unpenalized. There is no hyperparameter search. Each predictor is
standardized with its development-support mean and population standard
deviation (`ddof=0`); a zero/nonfinite deviation blocks that fit. Scaling values,
coefficients, source-column order, and support identifiers are frozen with the
fit and applied unchanged OOS.

Use deterministic full-batch L-BFGS-B from all-zero coefficients, `maxiter=2000`,
`ftol=1e-12`, `gtol=1e-8`, and no randomized initialization. A non-success
optimizer result, nonfinite coefficient, or final gradient infinity norm above
`1e-6` is `BLOCKED_MODEL`. Output probabilities must be finite, lie in `[0,1]`,
and sum to one within `1e-12`; otherwise the rung is blocked. No probability is
clipped except for the already-frozen calibration-slope diagnostic.

`M0` uses its full development complete-case support and compares OOS with the
three-cause development climatology on that support. `M0_COMMON` and `M1` are
separate fits on the exact same M1 complete-case development timestamps and
score on the exact same OOS timestamps. M1 lift is only against `M0_COMMON`.
Long-history M0 is context and cannot be used as M1's incremental comparator.
No validation/test refit, rescaling, calibration, or threshold retuning occurs.

## 6. Metrics, slices, and alert mechanics

D-032 metrics remain binding. The following completes their mechanical meaning:

- Directional Brier scores are computed on all equal-weight scoreable hourly
  rows. A family skill is the unweighted mean of its four direction x horizon
  relative Brier skills.
- A development alert threshold is the 99th percentile with
  `method="higher"`; alert iff `p > threshold`. Adjacent eligible hourly alerts
  one hour apart belong to one episode. Missing/ineligible timestamps close an
  episode.
- Episode precision is the share of alert episodes containing at least one row
  whose first cause is the target direction. The comparator base rate is the
  target-direction event rate over the same scoreable period and cell.
- Cluster recall and lead follow D-032. A primary cell with fewer than 30
  eligible clusters is reported but cannot support PASS.

Required non-gating descriptive slices are:

1. volatility `LOW/MID/HIGH`, using development-only `rv_24h` tertile cutpoints
   from `numpy.quantile(..., [1/3, 2/3], method="linear")`, then fixed OOS;
2. UTC session at `T`: `ASIA` [00:00,08:00), `EUROPE` [08:00,16:00),
   `AMERICAS` [16:00,24:00);
3. positive-cluster morphology `ONE_WAY/MIXED`, used only for cluster recall and
   lead diagnostics because it is a future outcome attribute; non-events are
   `NO_EVENT` and no morphology-conditioned Brier/calibration score is allowed.

EXP-004 records `NEWS_NOT_AVAILABLE` and performs no news slice. There is no
frozen point-in-time news corpus or pre-outcome taxonomy, and automated news
classification is excluded from v0. Post-hoc tagging would violate D-015/D-019.
This is non-gating for M0/M1 only; a news protocol remains mandatory before any
M2+ implementation. Every slice reports row, episode, and cluster counts where
defined; fewer than 30 clusters means report-only, not interpretation.

## 7. Mechanical rung dispositions for a later authorized run

Apply these rules separately to M0 versus climatology and M1 versus
`M0_COMMON`, after all three OOS periods are independently reported for both
fixed and twin families.

- `BLOCKED`: a causal source, risk-set, support, solver, probability, provenance,
  or metric-integrity requirement fails. A source-availability block is not a
  predictive verdict.
- `PASS`: in each of validation, test-2025, and test-2026, and in both fixed and
  twin families, family relative Brier skill is at least 1%; every one of the
  four primary cells has episode precision at least 2x its same-cell base rate,
  cluster recall at least 10%, median lead at least 15m for 1h or 60m for 4h,
  and at least 30 eligible clusters.
- `FAIL`: the run is valid and family relative Brier skill is at most -1% for
  both fixed and twin families in all three OOS periods.
- `NULL`: every other valid result, including inconsistent signs, immaterial
  lift, a missed alert gate, or insufficient primary-cell cluster count.

There is no pooled-period rescue, fixed-only PASS, slice rescue, or subjective
override. Confidence intervals and calibration diagnostics are reported but do
not replace these point-estimate gates. EXP-004 receives none of these model
dispositions until a later commission actually runs it.

## 8. Stop line

The only outputs authorized now are this contract, a source-availability audit
and its D-019 provenance, configuration/status synchronization, focused audit
tests, and the seat handover. Do not implement feature builders, risk-set labels,
the estimator, a fitting runner, or any score/report path. Stop before P6.
