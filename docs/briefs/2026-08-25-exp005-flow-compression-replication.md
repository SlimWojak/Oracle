# EXP-005 — Taker-flow variance-compression replication

CTO 2026-08-25. Frozen before label/effect inspection under the direct EXP-005
commission and D-037. This is one standalone, literature-anchored replication
of the exact D-033 flow construct against M0 on identical support. It is not a
partial M1, M1-lite, an EXP-004 rescue, M2, ignition, CVD, OFI, or a feature
search. M1 remains complete and `BLOCKED_ASOF`.

## 1. Question and belief change

Question: does exact D-033 `flow_compression_T` add prospective OOS information
and useful event selectivity beyond M0 on identical support?

- PASS: the frozen precursor generalizes to Oracle's broader prospective +/-2%
  population and becomes a validated standalone comparator. It does not unblock
  M1 or authorize M2+.
- FAIL: the valid frozen precursor is consistently harmful OOS; reject this
  operational replication.
- NULL: the run is valid but immaterial, inconsistent, insufficiently selective,
  or short of a required cluster floor; park it without another window or
  transform.
- BLOCKED: source, support, solver, provenance, or run integrity prevents a
  predictive verdict.

The motivating cascade study reports negative pre-onset Kendall trends in the
rolling variance of a detrended five-minute taker buy/sell log-ratio for all six
events with usable flow data. Its 300 ordinary-onset placebo distribution is
centered near zero; the paper calls the finding a population-level precursor,
not a per-event alarm (https://arxiv.org/html/2607.27070v1). The companion study
does not independently retest compression, but it verifies the Binance
metrics/kline interval-end versus interval-start alignment trap and treats large
OI clearing as an in-cascade signature
(https://arxiv.org/html/2608.03616v1).

EXP-005 is therefore a bounded operational replication, not an exact paper
reproduction. The paper uses the published five-minute metrics ratio and a
39-configuration detrend/variance/trend grid whose exact window values and
variance divisor are not enumerated; D-033 reconstructs the ratio from
one-minute quote volumes, freezes one 8h/2h population-variance level, applies
`-log`, and tests a different prospective population. The paper's six selected
cascades, one-venue design, moderate/window-sensitive effects, and placebos
drawn from the same six event files are carried as limitations. None of this
authorizes a window sweep.

## 2. Exact feature — no redesign or sweep

Source: Binance Vision USD-M BTCUSDT one-minute perpetual klines, using the
standard 12-position schema frozen in D-033. Raw `open_time` denotes interval
start. Normalize its epoch unit exactly; the causal interval end is
`open_time + 60s`. Preserve raw `close_time`, and reject a row whose close time
is before its open or after the nominal interval end. No alternate volume field
or aggregate metrics ratio is permitted.

For every UTC-aligned five-minute block ending at `s`, use the five exact
one-minute bars whose interval ends lie in `(s-5m, s]`:

```text
Q_s = sum(quote_volume)
B_s = sum(taker_buy_quote_volume)
S_s = Q_s - B_s
q_s = log(B_s / S_s)
```

Require all five unique bars, finite inputs, `B_s > 0`, and `S_s > 0`. Then:

```text
m_s = mean(q_v for v = s-475m, s-470m, ..., s)  # 96 points / 8h
e_s = q_s - m_s
v_T = mean((e_s - mean(e))**2
           for s = T-120m, T-115m, ..., T-5m)   # 24 points / 2h
flow_compression_T = -log(v_T)
```

Every one of the 96 `q` inputs for every residual and all 24 residuals is
required. `v_T` is the population variance (`ddof=0`) and must be positive and
finite. The newest block ends at `T-5m`; the complete raw lookback begins with
the bar ending at `T-599m`. No epsilon, partial window, forward fill, lag,
detrend, variance window, transform, or parameter sweep is allowed.

Duplicate handling is pre-effect and deterministic. Byte-identical duplicate
rows at the same normalized `open_time` are counted and collapsed once.
Differing rows at one timestamp are a conflict and make that minute unusable;
there is no file-order or last-write-wins resolution. Missing, off-grid,
noncausal-close, nonfinite, or conflicted minutes make every dependent block,
residual, and hourly feature missing.

## 3. Population, rungs, and estimator

Inherit D-032/D-033 unchanged: the D-022 hourly UTC prospective population,
strict trailing-15m precondition, categorical first cause, fixed and twin
families, D-023 periods, four-hour boundary purge, cluster-straddle discipline,
equal row/episode/cluster weights, primary cells, UTC-week dependence, slices,
and gap/ambiguity rules.

Fit separately for horizons `{1h,4h}` and label families `{fixed,twin}`:

1. `M0_COMMON`: the exact ordered seven D-033 M0 columns on flow-complete
   timestamps.
2. `M0_FLOW`: those same seven columns plus only `flow_compression_T`, last.

For each horizon and label family, both rungs must fit on the exact same
development timestamp identifiers and score on the exact same timestamp
identifiers in each OOS period. Any mismatch is `BLOCKED_SUPPORT`. Banked
long-support M0 is context only and is never the incremental comparator.

Reuse the D-033 deterministic baseline-category multinomial logistic estimator
without alteration: `NONE` reference, development mean/population-SD scaling,
ridge `lambda=1e-4`, unpenalized intercepts, full-batch zero-start L-BFGS-B,
`maxiter=2000`, `ftol=1e-12`, `gtol=1e-8`, final gradient infinity norm
`<=1e-6`, stable log-sum-exp probabilities, and probability sum tolerance
`1e-12`. No search, recalibration, OOS refit, or probability clipping outside
the frozen calibration diagnostic.

## 4. Checkpoint A — pre-effect source and support readiness

Checkpoint A may read causal price/source inputs and availability metadata. It
must not construct or inspect labels, future outcomes, validation/test scores,
feature-outcome relationships, or model effects.

The D-019 audit re-verifies every selected Binance manifest record against its
on-disk size and SHA-256 and records: archive identity, retrieval time, schema,
raw/normalized timestamp units and range, interval-start/end semantics, raw
close-time diagnostics, gaps, duplicates/conflicts, off-grid rows, out-of-order
rows, field finite/positivity counts, exact five-minute block availability, and
hourly feature availability.

Audit these UTC-hour periods separately:

- development: `2020-01-01T00:00:00Z` .. `2023-12-31T23:00:00Z`;
- validation-2024: `2024-01-01T00:00:00Z` .. `2024-12-31T23:00:00Z`;
- test-2025: `2025-01-01T00:00:00Z` .. `2025-12-31T23:00:00Z`;
- test-2026-01..07: `2026-01-01T00:00:00Z` ..
  `2026-07-31T23:00:00Z`.

The denominator for each period is every exact UTC hour inside the named
calendar bounds; period reporting additionally identifies the unchanged D-023
four-hour boundary-purge exclusions. `flow availability` means a finite exact
`flow_compression_T` at that hour. `M0_FLOW joint availability` means all seven
exact D-033 M0 columns and `flow_compression_T` are finite at that hour. These
are source/feature-availability masks only: no precondition outcome, label, or
future window is used. The later paired comparison takes the intersection of
this frozen feature mask, the unchanged D-032 eligibility mask, and scoreable
fixed/twin outcomes.

Required in every period:

- flow availability / candidate UTC hours `>=0.90`;
- `M0_FLOW` joint availability / candidate UTC hours `>=0.85`;
- no complete calendar month has zero `M0_FLOW` joint coverage.

The audit must independently reconfirm the D-033 causal ruling: source rows are
interval bars, each five-minute block is complete before use, and the latest
block ends at `T-5m`. Passing coverage cannot override a causality, manifest, or
hash failure. A source/causality/provenance failure banks `BLOCKED_SOURCE`; a
valid audit that misses a coverage floor banks `NULL_COVERAGE`. Either is a
terminal pre-effect EXP-005 verdict: update the public research record and stop
without substitution or label/effect inspection.

## 5. Checkpoint B — immutable implementation

Checkpoint B is authorized only if Checkpoint A clears.

Implement the exact flow builder, paired common-support rungs, inherited
metrics/reporting, and D-019 provenance in small modules. Focused tests must
cover:

- exact five-minute membership and the `T-5m` cutoff;
- missing bars and off-grid boundaries;
- strict `B_s/S_s` positivity;
- the exact 96-point detrend and 24-residual population variance;
- no epsilon, partial windows, or forward fill;
- identical `M0_COMMON`/`M0_FLOW` support;
- causal isolation from every post-`T` value.

Run `python -m unittest discover` and `ruff check .`. On the data host, run a
real development-only firewall that rejects any source or constructed outcome
at or after `2024-01-01T00:00:00Z`. It may fit development models and thresholds
but may not construct or inspect validation/test outcomes or effects. Freeze
scalers, coefficients, development thresholds, ordered source columns, and
cryptographic identifiers for every development support and pre-effect OOS
feature-support mask. Development diagnostics may not change the feature,
estimator, thresholds, or contract.

Bank one clean pre-OOS implementation commit before any OOS score. The OOS
runner must reject a dirty checkout or a commit other than that exact SHA.

## 6. Checkpoint C — one-shot execution

From the exact clean pre-OOS SHA and frozen development state, execute once on
the data host. Before constructing any OOS outcome, atomically consume one
machine-local receipt keyed by experiment and implementation SHA. A failed or
blocked consumed attempt is not a retry license.

Score validation-2024, test-2025, and test-2026-01..07 separately for fixed and
twin. Apply frozen development scalers, coefficients, and alert thresholds
without OOS refit. Emit complete population/support accounting; per-cell and
family Brier skill; calibration; alert episodes; precision; cluster recall;
lead time; volatility/session/morphology slices; family-wide UTC-week bootstrap
intervals; coefficients; frozen-state identifiers; and D-019 provenance.
Record `NEWS_NOT_AVAILABLE` as non-gating.

A result-affecting defect discovered after receipt consumption returns to the
Chair. Do not patch and rerun.

## 7. Mechanical model disposition

Apply the following to `M0_FLOW` versus `M0_COMMON` only after all three periods
and both label families are separately reported:

- PASS requires, in every period and both families, family relative Brier skill
  `>=0.01`; every primary direction x horizon cell has episode precision
  `>=2x` its same-cell base rate, cluster recall `>=0.10`, median lead `>=900s`
  for 1h or `>=3600s` for 4h, and at least 30 eligible clusters.
- FAIL requires a valid run with family relative Brier skill `<=-0.01` for both
  fixed and twin in all three OOS periods.
- Every other valid result is NULL, including inconsistent signs, positive
  Brier lift without actionability, insufficient cluster count, or any missed
  alert gate.
- A source, support, solver, probability, metric, provenance, or run-integrity
  failure is BLOCKED, not a predictive result.

There is no pooled-period, fixed-only, slice, coefficient, bootstrap, or
subjective rescue. A PASS is a bounded standalone result, not a definitive
predictive headline, and does not waive D-029's later untouched confirmation.

## 8. Stop line and close condition

EXP-005 cannot unblock or shrink M1; revive EXP-002/003/004; authorize M2-M5 or
armed-state work; introduce OI, funding, premium, CVD, OFI, ignition, or another
flow feature; start a source/vendor hunt; or add a dashboard, service,
automation loop, execution, or trading functionality.

The EXP closes only with either one banked exact-SHA mechanical model verdict or
one banked pre-effect source/support verdict. At close, synchronize D-037, the
ledger, glide path, configuration, `docs/HANDOVER.md`, workstation, origin, and
the data-host clone; run the full tests and Ruff; provide the five-item poll
packet; and stop for Chair review.
