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

## Operating model: thin orchestration

The lead agent session holds the CTO seat. It owns research judgment and must not
spend its context on mechanical work.

Reserved for the lead agent (never delegated):

- changes to `THESIS.md`, `RESEARCH_CONTRACT.md`, `DATA_CONTRACT.md`,
  `docs/DECISIONS.md`, and experiment verdicts in `EXPERIMENT_LEDGER.md`;
- experiment design, pass/fail interpretation, and anything touching label,
  split, or leakage semantics;
- review of all delegated output before it is committed.

Delegate to lighter Cursor-native models (Composer, Grok) via subagents:

- scaffolding, plumbing, and download/ingest scripts written to a frozen spec;
- mechanical refactors, formatting, boilerplate tests from a given spec;
- remote provisioning and long-running job supervision;
- broad codebase or literature searches whose output is a summary.

Delegation rules:

- Every delegated task carries a tight written spec with explicit file
  boundaries and acceptance checks.
- Delegated agents obey every fence in this file and may not edit the reserved
  documents above.
- The lead agent reviews delegated diffs before commit. Delegation transfers
  labour, not authority.

## Seat rotation

- Before ending a CTO session, update `docs/HANDOVER.md`: topology/access
  state, data on hand, in-flight jobs, verified load-bearing facts, next
  actions. Terse agent-to-agent prose.
- An incoming seat orients by reading `AGENTS.md`, then `docs/HANDOVER.md`,
  then `EXPERIMENT_LEDGER.md` and `docs/DECISIONS.md`, before touching code.

## Compute and data topology

- The canonical repository seat is the user's workstation; the remote headless
  data host (Tailscale name `dexter`) owns the immutable raw-data root and heavy
  data construction.
- Git is the only bridge between machines. Raw and derived data never enter the
  repository; scripts receive the data root as a parameter.
- On the data host, work only inside the Oracle repo clone and the Oracle data
  root. Other directories on that machine belong to unrelated projects and are
  out of bounds.

## Change discipline

- Prefer tiny composable modules and explicit contracts.
- Keep deterministic primitives separate from configurable research choices and
  interpretive conclusions.
- Add or update focused tests with every canonical logic change.
- Update `docs/DECISIONS.md` for accepted research or architectural decisions.
- Update `EXPERIMENT_LEDGER.md` only for actual experiment plans or completed runs;
  do not fabricate results.
- Run `python -m unittest discover` and `ruff check .` before handing off.
