# v0 research contract

## Primary question

Does direction-specific fuel interact with contemporaneous impact susceptibility
to raise the out-of-sample probability of a +/-2% BTC first passage within one or
four hours, and does aligned ignition add incremental timing information?

## Labels

- Consolidated BTC spot index, not a single perpetual venue.
- Fixed first-passage barriers: `+2%` and `-2%`.
- Horizons: `1h` and `4h`.
- A causal volatility-normalized twin is required, but its exact estimator must be
  accepted in `docs/DECISIONS.md` before implementation.
- If both barriers are touched inside one bar and ordering is unavailable, label the
  observation `AMBIGUOUS`; never guess.
- Adjacent positive timestamps belonging to one move form an event cluster for
  splitting, resampling, and inference.

## Hypotheses

- `H1_FUEL`: fuel changes vulnerability but is weak at timing.
- `H2_ARMED`: high fuel plus high impact susceptibility produces greater hazard than
  either component independently.
- `H3_IGNITION`: aligned signed flow adds timing information conditional on an armed
  state.
- `H4_ASYMMETRY`: upside and downside relationships may differ.
- `H5_EXOGENOUS`: precondition metrics may grade amplification even when the spark is
  externally generated.

## Frozen validation ladder

| Model | Inputs | Purpose |
|---|---|---|
| M0 | RV, trend, range, time controls | price-only baseline |
| M1 | M0 + OI, funding, premium, taker-flow variance | generic leverage/flow baseline |
| M2 | M1 + fuel challengers | path-local fuel increment |
| M3 | M2 + impact proxies separately | fragility increment |
| M4 | M3 + candidate interactions | armed-state test |
| M5 | M4 + ignition | timing increment |

No layer may be skipped in the reported ablation.

Taker-flow variance compression sits in M1 deliberately: it is the only
placebo-tested cross-event precursor in the motivating studies, so every
Oracle-specific family must demonstrate increment over it, not merely over price
controls.

## Pre-model descriptive gates

Before any interaction modelling (M4):

1. **Armed-quadrant occupancy.** Report the joint distribution of each fuel
   challenger against each impact proxy, including their correlation and the
   occupancy of the high-fuel/poor-absorption quadrant. Prior evidence found the
   analogous factors anticorrelated near -0.7, which would leave the armed cell
   too sparse to test. If occupancy is inadequate, record that verdict; do not
   proceed to H2 modelling on an empty cell.
2. **Trailing-path confounding.** Fuel is partly a deterministic function of the
   recent price path. Report the correlation of each fuel feature with trailing
   returns at the label horizons, and require that any claimed fuel lift in M2 is
   incremental to the M0/M1 controls that carry that path information.

## Two evaluation clocks

### Precondition clock

Samples market states before a material immediate impulse. It tests vulnerability
and advance warning. The exact impulse exclusion threshold is a research decision
that must be frozen before evaluation.

### Ignition clock

Starts after a prespecified small price or flow impulse. It tests continuation from
the current price into a subsequent first passage. Results must be described as
continuation detection when appropriate.

## Construct validation gates

Before predictive testing:

1. A fuel estimator must be evaluated against realized liquidation mass when its
   price bands are subsequently traversed. On Hyperliquid, realized mass must be
   split into book-hitting and backstop-absorbed components, because the venue
   backstop suppresses the propagation the estimator is meant to anticipate.
2. An impact proxy must be evaluated against subsequent realized slippage/impact for
   matched aggressive-flow sizes.

Failure here rejects the measurement implementation, not the market mechanism.

## Predictive validation

- Time-ordered development, validation, and final test periods.
- Purge and embargo at least the label horizon around split boundaries.
- Group event clusters across all splits, bootstraps, and confidence intervals.
- Report both timestamp count and independent event-cluster count.
- Require results across multiple contiguous OOS periods.
- Report calibration, precision at a fixed alert budget, recall, median lead time,
  and lift over each preceding model.
- Inspect descriptive monotonicity before fitting nonlinear models.
- Stratify results by direction, horizon, volatility regime, and event tag.

## Evaluation discipline (D-015, D-016, D-019)

1. **Robust regions, frozen grid.** Interaction evidence is reported on a
   coarse quantile grid (no finer than quintile x quintile) frozen before
   evaluation. The full grid is published with stability across years,
   horizons, and volatility regimes. No post-hoc region search; a single
   threshold that wins in one slice is not a finding.
2. **Family accounting.** Fuel challengers, impact proxies, and interaction
   forms are evaluated as families, not independent attempts. The interaction
   family (challenger x proxy x functional form) is the largest and most
   dangerous. A win at any ladder rung is incremental lift that beats the
   cluster-bootstrap distribution of the best-in-family statistic under a
   within-regime permutation null, not lift over zero. Killed measurement
   paths stay dead unless the estimator implementation changes, and re-enter
   only as a new ledger entry.
3. **Slice before model.** Before any M2+ fit, lift tables are reported by
   volatility regime, trading session, direction (squeeze vs dump), news-tag
   stratum, and mixed vs one-way cluster. Slices with fewer than 30 clusters
   are reported but not interpreted. Slices characterize a pooled
   pre-registered result; a story that lives only in one slice is recorded as
   a hypothesis for the next OOS period, not as a result.
4. **Common support.** Ladder comparisons are valid only on identical
   timestamp populations, labels, and missingness treatment. Each fuel
   challenger runs its own ladder on its usable history; incremental-lift
   comparisons between challengers run only on their common intersection.
   Adding a shorter-history feature must never silently change the test
   population. The long price-only history is context, never a comparable
   score.
5. **Episode-level evaluation.** Alert quality is scored on contiguous alert
   episodes and event clusters, never on repeated minute-level wins. A 4h
   cluster can last weeks; whether large clusters carry capped weight or one
   episode-level contribution is an open decision that must be settled before
   M2 scoring.
6. **Frozen news protocol.** News tags used in slicing are produced by a
   protocol frozen before model evaluation on that period. Tagging events
   after seeing model performance is prohibited.

## Interpretation matrix

| Evidence | Verdict |
|---|---|
| Fuel or impact proxy lacks construct validity | reject measurement path |
| Valid proxies but no OOS interaction lift | reject operational central thesis |
| Armed state predicts moves but not timing | vulnerability/risk-regime result |
| Ignition works only after a large move | continuation detector |
| Armed state plus early ignition gives stable lift | authorize richer research |
| Result exists only on Hyperliquid | venue-local result |

## v0 exclusions

- toxic-wallet identity;
- sub-second leader/lagger modelling;
- options surfaces;
- ADL ratings;
- cross-asset correlation fabrics;
- hidden-liquidity estimation;
- full replenishment modelling;
- automated news classification;
- dashboards or live services;
- trading and execution integration;
- a canonical monolithic score.

