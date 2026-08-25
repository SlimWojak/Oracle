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
- D-012 BANKED — HL fills Parquet/DuckDB; census parity PASS (13/13 exact)
- EXP-002 NULL — `cex_oi_cohort_v0` parked; no retry
- P5 BANKED — corrected prospective evaluation freeze
- D-033 BANKED — exact M0/M1 implementation contract and source-only D-019
  availability audit. M1 is `BLOCKED_ASOF` because OI/funding archives do not
  prove historical publication time.
- D-035 / EXP-004 M0 BANKED NULL — one exact-SHA run; no retune or rerun.
- D-036 / EXP-003 P4 BANKED BLOCKED — the pre-effect source audit found an
  unversioned ~5,000→20,000-USDC historical notional change and no authoritative
  quote-at-T publication semantics. No eligibility census, score, or one-shot
  run exists.
- D-037 / EXP-005 BANKED NULL — exact D-033 taker-flow compression against M0
  on identical support. Checkpoint A `79851be` was `CLEARED_CHECKPOINT_A`
  pre-effect; the one-shot sealed at `7fa0709` and evidence banked at
  `7ab09aa`. Parked without retry; no active work follows.

## Active path (order locked)

### P0 — Velocity substrate — **BANKED 2026-08-25**

Parquet/DuckDB (D-012) with hard parity vs banked EXP-001 census.

**Done:** PASS `reports/infra_hl_parquet_v1/parity.*` (13/13 exact). Derived store
on dexter: `{data_root}/derived/hyperliquid/fills/v1/all_fills` (10,912 source
hours, 3,460,998,856 rows, 82,512 zstd Hive parts). Builder wall 8h28m; parity
wall 1h54m after stream hotfix (PR #2). Provenance sidecar records dexter
working-tree SHA `086d9a8`; harness equivalent is main `7e2fab2`.

**Blocker lifted** for HL-derived science that *reads* the store. Next science
beat is still P1 (CTO freeze) — not self-authorized.

### P1 — Freeze construct designs — **BANKED 2026-08-25**

Chair four-cell ruling. D-029, D-030, D-031 accepted. Census banked with
D-019 provenance. 1h and `[2,4%)` parked (non-confirmatory).

**Primary family:** 4h × {up, down} × {(0,1%), [1,2%)}.

### P2 — Implement CEX-inferred fuel measurement path — **BANKED 2026-08-25**

Frozen spec: `docs/briefs/2026-08-25-p2-cex-fuel-path.md`.
Main `ed508e7` (PR #4): `cex_oi_cohort_v0` + 4h cluster-row + HL target hook.
No F. No P3 scoring in P2.

### P3 — Execute fuel construct gate — **BANKED NULL 2026-08-25**

Frozen spec: `docs/briefs/2026-08-25-p3-fuel-construct-gate.md`.
Reports `d591f9b`. Ledger EXP-002 **NULL**. Floor not locked (15/1000
dev week-draws undefined on n=12 up cells). Path parked. No silent retry.

**Done when:** PASS / FAIL / NULL recorded in the ledger.

**Kill:** failed paths do not enter predictive ladders. A materially changed
estimator re-enters only as a new EXP, never as a silent retry.

### P5 — Freeze evaluation unit (before baselines) — **BANKED 2026-08-25**

Chair swap: P5 ahead of P4. Frozen spec:
`docs/briefs/2026-08-25-p5-eval-unit.md` (corrected D-032). The original
event-only cluster unit was invalid and was superseded before any fit or score.
The banked unit is a causal hourly D-022 risk set with events and non-events,
categorical competing risks, a frozen price-impulse exclusion, explicit
timestamp/episode/cluster weights, and research-contract metrics. EXP-004 stays
PLANNED and unscored. No M0/M1 scoring. No P6 authorization.

**Done:** corrected D-032 and EXP-004 recorded; deterministic challenger history
regenerated from `index_clusters.json` with D-019 provenance; status and handover
synchronized; verification green. Inventory is not a scoring license.

### P4 — First impact construct gate — **BANKED BLOCKED_SOURCE 2026-08-25**

The post-M0 P4 commission froze the implementation-ready v4 contract at
`8e23b80`, then stopped at Checkpoint A. Evidence `23c838e` shows that the raw
quote schema contains no impact-notional/source-version or receive/publication
field. Effect-blind official L2 walks reproduce ~5,000 USDC in the first quoted
history and 20,000 USDC after a 2023-05-31 transition; available official
contract captures document 20,000 only and do not version the earlier regime.
Raw `time` is not authoritative public-availability evidence.

**Disposition:** EXP-003 `BLOCKED`. Eligibility census, scorer, correlation,
bootstrap, immutable implementation SHA, and one-shot receipt are all
`NOT_RUN_SOURCE_BLOCK`. No later-regime restriction, inferred schedule, or
trailing-realized-impact substitution is authorized. Return to Chair.

### P6 — Bank M0→M1, then stop — **M0-ONLY BANKED NULL; STOPPED**

Price-only and generic leverage/flow baselines on D-023 splits under the
frozen evaluation unit. D-033 freezes the seven-column M0, complete four-column
M1, deterministic joint multinomial estimator, common-support rule, reporting
slices, and mechanical rung dispositions. The label-blind source audit is banked
under `reports/exp004/m1_availability.*`.

M0 ran once from pre-OOS SHA
`680f2af101f88b55e761945390f6da020c9e9a71` and closed **NULL** under D-035.
All six period/family Brier-skill point estimates exceeded 1%, but the required
all-cell alert precision/recall/lead/count gates did not pass. No pooled, fixed-
only, slice, or uncertainty rescue applies.

M1 remains `BLOCKED_ASOF`: Binance metrics/funding bulk history has source
event timestamps but no historical publication/receive record or authoritative
latency guarantee. Kline-derived premium and taker-flow inputs clear interval-end
causality. Do not shrink M1 or invent a lag. Nothing after M0 is authorized.

**Done for the authorized rung:** M0 metrics, frozen state, NULL verdict, and
D-019 provenance are banked. P4 was later separately commissioned and banked
`BLOCKED_SOURCE`; stop for Chair review before any M1, M2+, replacement impact
source, or other authorization.

### Direct EXP-005 commission — **BANKED NULL; STOPPED**

D-037 permits one standalone literature-anchored replication of exact D-033
`flow_compression_T` against seven-column `M0_COMMON` on identical support. It
does not shrink/unblock M1 or authorize M2+. The pre-effect source audit banked
at `79851be`: all source/causality/provenance gates clear, all four period flow
and joint-coverage floors pass, and no month has zero joint coverage.

The development firewall passed at candidate `3e71902`; empty seal
`7fa0709011f451d0fc5ef95b5f4b5e7baf8152ed` preserved its exact tree. One
receipt was consumed and the valid no-refit run banked at evidence commit
`7ab09aa62b4392c61aa93d40752ca1ec3bd86efb`. Fixed/twin family Brier lift was
`0.1785% / -0.0040%` validation, `0.2180% / 0.0309%` test-2025, and
`0.1346% / -0.0305%` test-2026-01..07: all below the +1% PASS floor and far
from the stable -1% FAIL rule. Primary alert gates also miss. The mechanical
verdict is **NULL**. Park the construct; no alternate window, transform,
threshold, rerun, M1 change, or M2+ authorization follows.

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
- autonomy loops that widen the path without lead/reviewer authorization
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
the lead research seat. Reviewer sign-off is periodic, not required for routine
execution.

## Operating roles

- **Lead research seat:** one frozen commission at a time; bank verdicts; keep path.
- **Implementing subagents:** execute frozen specs only; no contract/ledger verdicts.
- **Advisory/reviewer seats:** decision-shaped takes only; cannot widen path.
- **Project owner:** may poll freely; not in the routine implementation path.

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
