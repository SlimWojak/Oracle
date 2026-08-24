# Oracle glide path (v1)

Banked 2026-08-24 (CTO + Chair synthesis). This is the active research sequence.
Completion of one beat does not self-authorize the next science beat.

## North star

Identify causal, point-in-time market states that reliably change the OOS
distribution of meaningful BTC moves: direction, magnitude, timing, and path.
Produce decision-relevant evidence, not trade instructions.

## v0 falsification target

Test whether direction-specific fuel × impact susceptibility raises OOS hazard
of ±2% BTC first passage (1h/4h), with ignition as timing-only.

If H2 fails: record FAIL/NULL; do not kill the laboratory; do not rescue fuel
as doctrine. The north star outlives any single v0 hypothesis.

## Banked state (as of lock)

- EXP-000 PASS — consolidated labels, D-023 splits, cluster discipline
- EXP-001 FAIL — HL-observed fuel demoted (D-024) to realized-mass diagnostics
  and construct-validation evidence only; no HL-fills predictive ladder this
  cycle (D-020)
- D-012 in flight — HL fills → Parquet/DuckDB; hard census parity required
  before further HL-derived science

## Active path (order locked)

### P0 — Velocity substrate

Bank Parquet/DuckDB (D-012) with hard parity vs banked EXP-001 census.

**Done when:** PASS parity report on main and derived store on the data host.

**Blocker:** no new HL-derived EXP until this banks.

### P1 — Freeze construct designs

CTO freezes short designs for:

1. Fuel construct: challenger vs subsequently traversed realized liquidation
   mass (book-hitting and backstop mass remain separate).
2. Impact construct: impact proxy vs matched realized slippage.

**Done when:** brief(s) + ledger EXP stubs (PLANNED) with pass/fail metrics and
actionability contracts (below).

### P2 — Implement CEX-inferred fuel measurement path

First predictive-path fuel family with usable history (D-016 / D-020).
Point-in-time public metrics → causal fuel features. No vendor heatmap yet.

**Done when:** feature code, as-of rules, and hooks for the P3 gate exist.
No M2 fit until construct has a recorded verdict.

### P3 — Execute fuel construct gate

Run the frozen fuel construct EXP.

**Done when:** PASS / FAIL / NULL recorded in the ledger.

**Kill:** failed paths do not enter predictive ladders. A materially changed
estimator re-enters only as a new EXP, never as a silent retry.

### P4 — Implement and execute first impact construct gate

Build the first impact proxy path, then run its frozen construct EXP.

**Done when:** PASS / FAIL / NULL recorded. Book≠backstop discipline preserved
wherever mass is referenced.

### P5 — Freeze evaluation unit (before baselines)

Settle before any M0/M1 banking:

- timestamp / risk-set construction and negative dependence
- cluster or episode weighting
- alert-episode scoring
- volatility-normalized barrier twin **estimator** (D-026: twin is a finding
  blocker — no PASS headline on fixed ±2% alone)
- primary vs exploratory cell budget for ladder reports (D-025)
- regenerate `challenger_history` from `index_clusters.json`

Open as decision debt when P0 banks; must be settled before P6 scoring.

**Done when:** decisions recorded in `docs/DECISIONS.md` (and inventory regen
committed if required).

### P6 — Bank M0→M1, then stop

Price-only and generic leverage/flow baselines on D-023 splits under the
frozen evaluation unit.

**Done when:** baseline metrics banked; stop for Chair/CEO review before any
M2+ authorization.

## Post-authorization only (not self-starting)

After Slim/Chair authorization of further ladder work:

1. Trailing-path confounding (and required population slices) before interpreting M2 fuel lift
2. M2 (fuel increment)
3. M3 (impact increment)
4. Armed-quadrant occupancy (requires surviving fuel **and** impact measures) immediately before M4
5. M4 (interactions)
6. M5 / ignition only after armed-state evidence

Armed occupancy must not run before both construct paths have surviving measures.
If occupancy is inadequate: H2 dies descriptively (D-027) — record NULL/FAIL;
follow-ons are new EXP stubs only, not a same-day redesign or M4 on an empty cell.

Fixed ±2% work may proceed for construct/descriptive beats; **claimed findings
and PASS headlines** require the vol-normalized twin alongside (D-026).
Ladder PASS headlines may cite primary cells only (D-025).

## Anti-goals (this glide)

- `replica_cmds` / L1 wallet reconstruction spend without an explicit sized decision
- vendor fuel surfaces without verified as-of history
- self-commissioned science beats
- platform, dashboards, live services, trading/execution
- averaging or quietly reviving dead challengers
- silent estimator retries after FAIL
- Owl/autonomy loops that widen path without CTO/Slim
- PASS headlines from exploratory cells or fixed-barrier-only claims (D-025, D-026)

## Post-P0 hygiene (not a science beat)

After P0 banks: thin Engineer commission for **golden / byte-identity pins** on
deterministic primitives (labels, clusters, index, stratification classification,
Parquet schema) using tiny fixtures — same inputs, same bytes, unittest-guarded.
Complements D-019; does not gold-pin the full fill tape. Does not authorize P1+.

## Bounded travel

Completing a beat does not self-authorize the next science beat.

Agents may finish mechanical subtasks inside the active frozen commission.
A construct verdict, kill/park trigger, or ladder boundary returns judgment to
the CTO. CEO/Chair review is periodic, not required for routine execution.

## Operating roles

- **CTO:** one frozen commission at a time; bank verdicts; keep path.
- **Engineer:** execute frozen specs only; no contract/ledger verdicts.
- **Advisors (Owl/Chair):** decision-shaped takes only; cannot widen path.
- **CEO (Slim):** poll freely; not in the critical path of P0–P5.

## EXP stub minimum (actionability contract)

Every experiment stub states:

- **Belief change:** what PASS, FAIL, or NULL changes.
- **Materiality:** minimum lift, lead time, and selectivity worth caring about.

## Daily poll packet

When reporting status upward, use:

1. Active beat
2. Evidence banked
3. Deviations / blockers
4. Next judgment point
5. Proposed next bounded action

## Kill / park triggers

- D-012 parity FAIL after honest debug → stop HL science; escalate
- Construct FAIL on a challenger → demote that path; do not average in substitutes
- Armed cell inadequate (when reached) → H2 dies descriptively (D-027); NULL/FAIL; do not proceed to M4; no same-day redesign
- Any PR that adds predictive features without a ledger EXP → reject
- PASS headline from exploratory cells or without vol twin (D-025, D-026) → reject
