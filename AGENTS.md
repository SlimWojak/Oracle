# Oracle agent instructions

## Mission

Oracle is an isolated BTC-perpetual research laboratory. Its purpose is to test and
falsify hypotheses about directional fuel, impact susceptibility, ignition, and
large first-passage moves. It is not part of any other user project.

Before making material changes, read:

1. `THESIS.md`
2. `RESEARCH_CONTRACT.md`
3. `DATA_CONTRACT.md`
4. `docs/DECISIONS.md`
5. `EXPERIMENT_LEDGER.md`

## Hard boundaries

- Do not connect Oracle to production systems, brokers, execution, portfolio
  management, or the user's other repositories.
- Do not place trades or add trading controls.
- Do not build a dashboard, API, daemon, scheduler, generic runner, agent framework,
  or real-time platform unless the user explicitly authorizes that expansion.
- Do not add Aura, ATOM, Ichimoku, strategy-curator, constellation, or inherited
  methodology dependencies.
- Do not commit raw or licensed market data, credentials, secrets, or machine-local
  paths.
- Do not silently turn liquidations, OI collapse, or post-onset volatility into
  predictive features. Preserve stage semantics.
- Do not collapse Hyperliquid observations, CEX inference, and vendor heatmaps into
  one canonical fuel metric.
- Do not canonize `fuel / absorption` as the only interaction form. The ratio is one
  candidate specification.
- Do not use subjective exogenous/endogenous tags as model inputs in v0.
- Do not add a feature family before the previous validation layer has a recorded
  verdict.

## Scientific discipline

- Every feature must be causal and computable with information available as of the
  decision timestamp.
- Preserve source timestamp, receive timestamp where available, interval convention,
  sequence, and as-of availability.
- Treat adjacent labels from one market move as an event cluster, not independent
  observations.
- Distinguish construct invalidity from predictive invalidity.
- Separate precondition tests from ignition/continuation tests.
- Compare simple components, additive forms, interactions, ratios, and log ratios.
- Require descriptive monotonic evidence before nonlinear model complexity.
- Use time-ordered, purged out-of-sample validation. Never random-split market time.
- Record negative, null, ambiguous, and blocked results in `EXPERIMENT_LEDGER.md`.
- Notebooks may explore; canonical transformations and metrics belong in tested code.

## Change discipline

- Prefer tiny composable modules and explicit contracts.
- Keep deterministic primitives separate from configurable research choices and
  interpretive conclusions.
- Add or update focused tests with every canonical logic change.
- Update `docs/DECISIONS.md` for accepted research or architectural decisions.
- Update `EXPERIMENT_LEDGER.md` only for actual experiment plans or completed runs;
  do not fabricate results.
- Run `python -m unittest discover` and `ruff check .` before handing off.
