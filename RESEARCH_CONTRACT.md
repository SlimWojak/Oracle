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
| M1 | M0 + OI, funding, premium | generic leverage baseline |
| M2 | M1 + fuel challengers | path-local fuel increment |
| M3 | M2 + impact proxies separately | fragility increment |
| M4 | M3 + candidate interactions | armed-state test |
| M5 | M4 + ignition | timing increment |

No layer may be skipped in the reported ablation.

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
   price bands are subsequently traversed.
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

