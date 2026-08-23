# Oracle thesis

## Working claim

A sharp BTC move becomes more probable when direction-specific forced inventory
near the current price is large relative to the market's ability to absorb flow
along that path, and a signed impulse begins while impact susceptibility is high.

This is an interaction thesis, not a claim that any one scalar is a universal crash
alarm.

For direction `d`, distance `x`, and horizon `H`, the research object is:

```text
P(first passage of x in direction d within H)
    = f(fuel_d, impact_susceptibility_d, ignition_d, regime)
```

A pathwise ratio is one candidate representation:

```text
SweepRatio_d(x, t) = estimated forced notional_d([0, x], t)
                     / estimated effective absorption_d([0, x], t)
```

Oracle must also test the numerator, denominator, additive form, interaction form,
and log-difference separately. A noisy denominator can manufacture an extreme ratio.

## Position relative to prior evidence

The motivating studies (arXiv:2607.27070, arXiv:2608.03616) tested seven historical
cascades and report three results Oracle must not ignore:

1. No scalar pre-state measure graded cascade severity: not leverage stock, not
   measured book fragility, and not their product. The branching product
   `k * rho` self-cancelled because its factors were strongly anticorrelated
   (`corr(log k, log rho) ~ -0.7`).
2. The one placebo-tested, cross-event invariant precursor was compression of
   taker buy/sell flow variance before onset - a population-level signal, not a
   per-event alarm.
3. The single pre-state candidate their designs could not test is the accumulated
   map of liquidation thresholds near price: a measure swept by the path, not a
   scalar.

Oracle's claim to novelty is therefore specific: the distance-indexed, directional
fuel surface is a discretization of exactly the untested path-swept map, and the
target population is common +/-2% first passages rather than seven record
cascades, which escapes the n=7 sample problem.

Known threats inherited from that evidence:

- Fuel and impact susceptibility may be mechanically anticorrelated, leaving the
  armed cell (high fuel and poor absorption) nearly unpopulated. This must be
  checked descriptively before any interaction modelling.
- Fuel near price is partly a deterministic function of the trailing price path
  (a decline drags long liquidation levels toward price). Fuel lift must be shown
  conditional on trailing-return controls, or it is repackaged momentum.
- The observed Hyperliquid topology is propagation-damped by design: the venue
  backstop absorbed roughly two thirds of forced notional off-book in the record
  cascade. HL-observed fuel validates measurement methodology, not cascade
  mechanics.

## Durable deductions

1. Leverage is fuel, not a clock.
2. Vulnerability is directional and distance-indexed.
3. Exogenous sparks need not have advance market-data signatures.
4. Liquidations and OI clearing usually measure propagation, not prediction.
5. A venue-local liquidation topology is not the global BTC topology.
6. Displayed book depth is not equivalent to effective absorption under stress.
7. Selective warning with useful lead time is a credible objective; universal
   prediction is not.
8. A risk-off, do-not-fade, or size-down result remains useful even if direct entry
   timing fails.

## Atomic research objects

### Fuel

Maintain independent challengers:

- observed Hyperliquid liquidation topology (provisional: the fill tape proves
  realized liquidation mass and routing, but cross-margin liquidation prices
  depend on account state, not fills alone; "observed" is earned only if
  EXP-001 demonstrates honest pre-state reconstruction at time t, per D-018);
- internally inferred CEX topology from causal public data;
- vendor/model topology.

Do not average them before each has independent construct and predictive evidence.

### Impact susceptibility

v0 intentionally avoids claiming to measure full hidden liquidity or effective
absorption. Candidate proxies are:

- causal visible book-walk slippage at normalized sizes;
- trailing realized price response per signed aggressive dollar.

These remain separate until evidence supports a composite.

### Ignition

v0 candidates are signed OFI/CVD acceleration and spot-led versus perp-led impulse.
Ignition tests operate on a separate clock from precondition tests so continuation
is not misrepresented as advance warning.

### Flow state

Taker buy/sell flow-variance compression (aggressive flow going persistently
one-sided) is a precondition-clock candidate. It is the only placebo-tested
cross-event precursor in the motivating studies and enters as its own family, not
as an ignition-timing signal.

### Propagation

Realized liquidations, return-conditioned OI clearing, impact expansion, and
cross-venue synchronization identify propagation or exhaustion. They are outcomes
or stage variables unless strict timing proves otherwise.

## State language

- `DORMANT`: no unusual fuel or fragility.
- `LOADED`: direction-specific fuel is elevated.
- `ARMED`: fuel is elevated while impact susceptibility is poor.
- `IGNITING`: signed flow begins in the vulnerable direction.
- `PROPAGATING`: forced flow and deleveraging are observable.
- `EXHAUSTED`: fuel clears or absorption recovers.

The state language is interpretive output. It must not become hand-labelled truth
used to train itself.

## Open questions

- Can a local transparent-venue topology validate a portable CEX estimator?
- Does fuel alter hazard without providing timing?
- Does poor absorption interact with fuel beyond additive effects?
- Does aligned ignition add lead time before a meaningful fraction of the move has
  already occurred?
- Are upside squeezes and downside cascades structurally asymmetric?
- Does any result survive multiple contiguous out-of-sample regimes?

