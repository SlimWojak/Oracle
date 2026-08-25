# Decision record

## D-001 — Standalone research boundary

**Accepted.** Oracle is unrelated to the user's other work and has no production,
trading, or orchestration dependency.

## D-002 — Interaction thesis, not ratio canon

**Accepted.** `fuel / absorption` is one candidate representation. Components,
additive forms, interactions, ratios, and log differences must be compared.

## D-003 — Parallel fuel challengers

**Accepted.** Hyperliquid-observed, internally inferred CEX, and vendor/model fuel
surfaces remain separate until independently validated.

## D-004 — Impact susceptibility terminology

**Accepted.** v0 does not claim to estimate complete effective absorption. Visible
book-walk and trailing realized-impact proxies remain separately named.

## D-005 — Separate research clocks

**Accepted.** Precondition and ignition/continuation experiments are evaluated and
reported separately.

## D-006 — Two invalidity classes

**Accepted.** Construct invalidity rejects a measurement path. Predictive invalidity
after construct validation may reject the operational thesis.

## D-007 — First-passage scope

**Accepted.** v0 uses consolidated-index +/-2% first passage at 1h and 4h, mirrored
upside/downside. A volatility-normalized twin is required but not yet specified.

## D-008 — No platform before evidence

**Accepted.** No live service, dashboard, generic runner, execution connection, or
expanded feature programme is authorized by the v0 scaffold.

## D-009 — Prior-evidence refinements

**Accepted.** Motivated by arXiv:2607.27070 and arXiv:2608.03616: taker-flow
variance compression joins M1 as the strongest prior-evidence baseline; an
armed-quadrant occupancy gate and a trailing-path confounding report are required
before interaction modelling; Hyperliquid construct validation splits book-hitting
from backstop-absorbed liquidation mass; the Binance metrics/kline interval
convention trap and the fill-log deduplication rule are binding in
`DATA_CONTRACT.md`.

## D-010 — Compute and data topology

**Accepted.** The user workstation is the canonical repository seat. The headless
data host (`dexter`) owns the immutable raw-data root and heavy data
construction. Git is the only bridge; data never enters the repository.

## D-011 — Thin orchestration

**Accepted.** The lead agent holds research judgment and reviews everything;
mechanical, well-specified work is delegated to subagents selected for the needed
capability, reliability, and cost/latency profile. No model vendor or named provider
is part of the architecture. Contract documents, experiment design, and verdicts
are never delegated. Details in `AGENTS.md`.

## D-012 — Analytical store

**Accepted.** DuckDB over Parquet files, rebuildable from raw plus manifests. No
database server or hosted store in v0.

## D-013 — v0 label price source and venue-replication gate

**Accepted.** v0 labels use Binance spot 1m klines as the primary price. Once the
event catalogue exists, every labelled event is re-checked against a second spot
venue (Kraken). Non-replicating events are flagged `VENUE_DISPUTED` and excluded
from headline results. If the disagreement rate exceeds 2% of events, a
median-of-three consolidated index must be built before predictive work. The
contract's core requirement stands: labels are never taken from a perpetual
venue.

## D-014 — Event-cluster definition

**Accepted.** Two positive anchors belong to one cluster when their decision
timestamps are within one label horizon of each other or their passage windows
overlap. A cluster closes only after a full 4h window without a positive anchor.
Direction is recorded per anchor; clusters containing both directions are marked
mixed. Splits, bootstraps, and sample counts operate on clusters. The definition
deliberately errs toward merging, since pseudo-replication is the feared failure
mode.

## D-015 — Evaluation discipline: regions, families, slices

**Accepted.** Three user-seeded rules, adopted with modifications: interaction
evidence on a pre-frozen coarse quantile grid published in full; family-level
accounting with best-in-family bootstrap nulls (the interaction family counted
as one family across challengers, proxies, and forms); population slicing
before modelling with a 30-cluster interpretation floor, slices characterizing
rather than rescuing pooled results. Details in `RESEARCH_CONTRACT.md`.

## D-016 — Common-support rule for ladder comparisons

**Accepted** (advisor review, 2026-08-23). Fuel challengers have very different
usable histories (CEX-inferred metrics from 2021-12, HL impact context from
2023-05, HL fills from 2025-05). Each challenger is evaluated on its own ladder
over its usable period; head-to-head and incremental-lift comparisons run only
on the common intersection with identical timestamps, labels, and missingness
treatment. Adding a shorter-history feature must never silently shrink the test
population. The long price-only history is context, never a comparable score.

## D-017 — Canonical decision timestamp is the interval end

**Accepted** (advisor review, 2026-08-23). A label anchored on a bar's close is
knowable only at interval end, so the canonical decision timestamp for
bar-anchored labels is `open_time + 60s`, not the Binance interval-start stamp.
The EXP-000 catalogue originally stamped anchors at interval start; code fixed
and catalogue rebuilt before any feature alignment, embargo, or split boundary
was frozen. Counts unaffected; all anchor/passage timestamps shifted +60s.

## D-018 — Hyperliquid-observed fuel is provisional pending EXP-001

**Accepted** (advisor review, 2026-08-23). The fill tape proves realized
liquidation mass, book/backstop routing, and aggressor flow, but under
cross-margin a liquidation price depends on account value, other positions,
funding, and margin state — not fills alone. "HL-observed fuel" therefore
remains a provisional construct until EXP-001 demonstrates honest pre-state
topology reconstruction at time t. If reconstruction fails, the HL challenger
is demoted to realized-mass diagnostics and construct validation.

## D-019 — Reporting and provenance hygiene

**Accepted** (advisor review, 2026-08-23). Three rules: (1) alert quality is
evaluated on contiguous alert episodes and event clusters, never repeated
minute-level wins; (2) any news-tagging protocol is frozen before model
evaluation on a period — tagging after seeing performance is prohibited;
(3) every data-host run producing committed evidence records the repo commit
SHA, configuration hash, input manifest identifiers, UTC execution time, and
output content hashes.

## D-020 — HL-fills challenger runs no predictive ladder this cycle

**Accepted** (user sign-off, 2026-08-23). The Hyperliquid fill tape's usable
history (2025-05-25 to the catalogue end 2026-07-31) falls entirely inside the
final-test region of any regime-diverse chronological split and contains too
few independent clusters (~170 at 1h) to support a nested development/
validation/test design. In this cycle the fill tape therefore serves EXP-001
reconstruction feasibility, construct validation (realized liquidation mass
with book/backstop split), and realized-mass diagnostics only; no predictive
ladder is fitted on an HL-fills-derived fuel feature. The challenger earns a
ladder in a later cycle when its history extends, consistent with D-016
(own ladder on own usable history) and D-018 (observed status gated on
EXP-001). The nested-split alternative was considered and rejected as
statistically uninterpretable.

## D-021 — Venue-replication check semantics (operationalizes D-013)

**Accepted** (2026-08-23). The D-013 Kraken re-check runs at event-cluster
level with these frozen rules:

1. **Unit and window.** Each Binance-labelled cluster (first anchor decision
   timestamp T0, cluster end T1, horizon h, threshold 2%) is checked once per
   horizon. Kraken bars are labelled with the identical first-passage code
   (same threshold, horizon, interval-end decision timestamps) on Kraken's
   own price series; the cluster replicates when at least one positive
   Kraken anchor with a direction present in the cluster falls in
   [T0 - h, T1]. Mixed clusters replicate on either direction.
2. **Own-venue reference prices.** Each venue's passage is measured from its
   own bar closes. XBTUSD (USD) versus BTCUSDT (USDT) basis drift therefore
   cancels within-venue; disagreement during stablecoin-stress periods is
   informative signal, not measurement error.
3. **Structural sparsity is not disagreement.** Kraken omits no-trade
   minutes (30,186 missing in 2020 falling to 2,362 by 2025). If Kraken bar
   coverage over [T0 - h, T1 + h] is below 90%, the cluster is flagged
   `KRAKEN_SPARSE` and excluded from the disagreement-rate denominator;
   sparse counts are reported alongside. Only well-covered non-replicating
   clusters become `VENUE_DISPUTED`. The D-013 2% escalation threshold is
   evaluated on the well-covered population per horizon.
4. **Coverage boundary.** Official Kraken bars end 2026-03-31; clusters
   whose check window extends past that date are deferred until the
   normalization layer builds bars from the raw trade pages, and are
   reported as `PENDING_BARS` rather than silently skipped.

**Interpretation caveat (2026-08-23, advisor review).** The match window
[T0 - h, T1] admits Kraken anchors whose passage completes up to one horizon
after the Binance cluster end, which biases toward replication. Exceeding the
2% escalation threshold despite that generosity makes the escalation robust,
but the disagreement statistic must not later be read as a measure of precise
cross-venue synchronization.

**Correction (2026-08-23, same seat, before any committed gate result).**
Rule 1 originally said Kraken bars are labelled "with the identical
first-passage code". The identical bar-count labeller is wrong on a venue
with structural no-trade gaps: fixed bar-count windows are undefined across
gaps, and restricting to contiguous segments under-detects passages exactly
where gaps are dense (2020 Kraken fragments into 24,261 segments of median
length 6 bars, making 4h passages nearly undetectable and inflating the
disputed rate to 22% at 4h in a diagnostic run). The venue labeller is
therefore time-aware: every bar anchors a wall-clock window
(close, close + h minutes] evaluated over the bars that exist in it, same
threshold and interval-end decision timestamps. Bar-count and wall-clock
windows coincide wherever bars are contiguous, so this changes nothing on
the primary venue. A venue anchor crossing both barriers in one bar counts
toward either direction.

## D-022 — Median-of-three consolidated label index

**Accepted** (2026-08-23, frozen blind: adopted while the Coinbase pull was
still running, before any Coinbase data or its effect on the catalogue was
inspected). Executes the D-013 escalation.

1. **Members, fixed.** Binance BTCUSDT spot, Kraken XBTUSD spot, Coinbase
   BTC-USD spot, 1m bars. No further label venues will be added. Kraken bars
   are the official OHLCVT export through 2026-03-31 and the exact-validated
   trades-derived bars for 2026-04-01..2026-07-31.
2. **Availability rule.** An index minute exists iff at least two members
   have a bar. Each index bar records a `3_OF_3` or `2_OF_3` flag.
   Single-venue minutes produce no index bar. No venue is ever
   forward-filled across its gaps.
3. **Construction.** Componentwise median of available members for open,
   high, low, and close (the median of two is their midpoint). Volume is the
   sum of available members, carried as a diagnostic only — labels never use
   it. Source interval-start stamps; decision timestamps remain interval end
   (D-017).
4. **Quote basis.** No USD/USDT adjustment. With two USD members and one
   USDT member, the median follows the USD majority during stablecoin
   stress; this is intended behavior for a consolidated BTC index and is
   documented rather than corrected. The sensitivity report must slice any
   window where members diverge materially.
5. **Label semantics on the index.** First-passage labels use wall-clock
   horizons exactly as in the D-021 correction: every index bar anchors a
   window (close, close + h minutes] evaluated over the index bars that
   exist in it; absent minutes contribute no evidence. The same-bar
   ambiguity rule is unchanged. On near-complete grids this coincides with
   the bar-count labeller.
6. **Sensitivity report, required before splits are frozen.** Binance-only
   versus consolidated catalogue: clusters retained, added, removed;
   direction flips; anchor and passage timing shifts; mixed-cluster
   changes; breakdowns by year and volatility regime; and the share of
   positive anchors whose bars are `2_OF_3`.

## D-023 — Initial chronological split boundaries

**Accepted** (user sign-off, 2026-08-24). On the D-022 consolidated
catalogue: development 2020-01-01..2023-12-31 (1,182 one-hour clusters;
COVID crash, 2021 mania and unwinds, 2022 Luna/FTX bear, 2023 chop);
validation 2024-01-01..2024-12-31 (235); final test 2025-01-01..2026-07-31
(241), scored as two contiguous OOS periods (2025 and 2026-01..07). Any
cluster whose span padded by one 4h horizon crosses a boundary is dropped
from both sides (stricter than the contract's minimum purge/embargo). Per
D-016, all challenger ladders share the final-test period; the CEX-inferred
ladder develops on 2021-12..2023-12 and validates on 2024; the HL
impact-context ladder develops on 2023-05-20..2024-06-30 and validates on
2024-07-01..2024-12-31; head-to-head comparisons run only on common
intersections. The HL fill tape runs no ladder this cycle (D-020). The
validation year is thin (235 clusters) but the alternative — validating on
2025 — would leave a single-period final test, which the contract forbids.

## D-024 — EXP-001 FAIL executes D-018 demotion

**Accepted** (2026-08-24, Grok Bot CTO seat). EXP-001 closed FAIL: Phase 1
tractable notional share 39.06% (below 50% partial-viability) and Phase 2
coverage-weighted reconstruction accuracy 8.02% (below 90% PASS). The
Hyperliquid-observed fuel challenger is demoted from provisional observed fuel
to **realized-mass diagnostics and construct-validation evidence only**. No
predictive ladder on HL-fills-derived fuel this cycle (consistent with D-020).
Fill tape retained. `replica_cmds` / L1 account-state pulls are not authorized
by this demotion; reopen only with an explicit sized spend decision.

## D-025 — Primary vs exploratory evaluation cells

**Accepted** (2026-08-24, CTO; constellation fresh-eye seed). Family accounting
and the frozen coarse quantile grid (D-015) remain binding. In addition, every
ladder report names a **primary cell set** that is pre-registered before
evaluation on that period. Primary cells are few (default sketch: both
directions × both horizons on the frozen coarse grid; at most one pre-registered
regime slice). All other cells — finer grids, extra regime cuts, post-hoc
interactions of challenger × proxy × form — are labelled **exploratory** and
**cannot headline a PASS**. Exploratory tables may be published for diagnosis
only. Exact primary-cell enumeration for v0 baselines is settled with the
evaluation-unit freeze (glide path P5) before M0/M1 banking.

## D-026 — Vol-normalized twin is a finding blocker

**Accepted** (2026-08-24, CTO; constellation fresh-eye seed). The
volatility-normalized barrier twin remains required (D-007). Strengthening:
**no claimed finding or PASS headline** may rest on fixed ±2% barriers alone.
Fixed-barrier labels may still be used for construct validation, descriptive
audits, and scaffolding, but any predictive PASS / material claim must report
the twin alongside (or justify a recorded exception). Exact twin estimator is
still an open decision; it must be accepted before P6 baseline banking if
baselines are to be treated as findings, and in any case before any M2+ PASS
headline.

## D-027 — Empty armed-cell outcome is pre-decided

**Accepted** (2026-08-24, CTO; constellation fresh-eye seed). If
armed-quadrant occupancy is inadequate when that gate is reached, **H2 dies
descriptively** for that challenger/proxy family: record NULL or FAIL for the
interaction claim. That day is not a redesign license. Allowed follow-ons are
**new EXP stubs only** (examples: H4 asymmetry; occupancy conditional on a
pre-registered regime slice). They do not reopen the failed occupancy cell as
the same EXP, and they do not authorize M4 modelling on an empty cell.

## D-028 — D-012 Parquet store banked (P0)

**Accepted** (2026-08-25, CTO). The Hyperliquid fills derived store is the
canonical analytical source for HL fill/liquidation queries: Hive-partitioned
zstd Parquet under `{data_root}/derived/hyperliquid/fills/v1/all_fills`, rebuilt
from raw LZ4 via `scripts/build_hl_btc_liquidations.py`. EXP-001 Phase 1 census
parity against `reports/exp001/stratification_census.json` is PASS (13/13 exact;
artifacts `reports/infra_hl_parquet_v1/parity.*`). Full-tape LZ4 scans are no
longer the default path for census-class work. Raw LZ4 remains the immutable
source of truth for rebuilds.

## D-029 — Construct / predictive test-period firewall

**Accepted** (2026-08-25, Chair signed the written policy). Hyperliquid fill ground truth begins 2025-05-25 and lies
inside the D-023 final-test region. Realized liquidation mass and ±2% labels
are correlated.

Frozen policy:

1. Construct-dev (SE / coverage / floor lock only): 2025-05-25 .. 2025-08-31.
2. Construct-val (P3 / P4 locked score): 2025-09-01 .. 2025-12-31.
3. First predictive look: 2026-01-01 .. 2026-07-31. Untouched for kernels,
   bands, sizes, windows, or floors.
4. **Second confirmation: 2026-08-01 .. 2026-12-31.** No definitive
   predictive PASS headline before this window closes and meets the frozen
   cluster floors (30 eligible clusters per direction×horizon).
5. 2025 D-023 OOS is spent for construct and must not also tune predictive
   features.

Rejected alternatives: a joint no-adaptation gatekeeping test on the whole
final-test region (spends 2026); declaring the entire final-test spent;
leaving “a later contiguous period” unspecified.

## D-030 — CEX fuel is a four-cell quantity-cohort proxy

**Accepted** (2026-08-25, Chair four-cell ruling). Pre-outcome feasibility
correction: the path-only eligibility census inspected no fuel values and
no HL liquidation mass.

Challenger `cex_oi_cohort_v0`: causal entry-price cohort memory of signed
Binance UM `sum_open_interest` quantity changes, side-split by
`sum_toptrader_long_short_ratio`. Opening stock sits in an unallocated
no-price bucket. Surviving quantities valued at P_T.
`sum_open_interest_value` is the OI-only USD baseline, never the cohort Δ.

**Primary family:** 4h × {up, down} × {(0,1%), [1,2%)}. Coverage:
construct-dev ≥10 per cell, construct-val ≥15. No further relaxation.
PASS is M2-eligibility for these 4h cells only. 1h and `[2,4%)` are
parked and non-confirmatory. F is the equal-weight four-cell statistic.
Shape: m3≥m1 in ≥3/4 cells, zero hard flips. Bootstrap: one family-wide
weekly draw carrying linked rows across both bands. Stability: Sep–Oct
and Nov–Dec 2025 (≥10/cell, defined F, positive incremental F). If a
primary cell later falls below its floor, NULL, not a redesign.

Details: `docs/briefs/2026-08-25-p1-fuel-construct.md` v5, EXP-002,
`reports/p1_eligibility_census.json`.

## D-031 — First impact proxy is quoted book-walk; match unit frozen

**Accepted** (2026-08-25, Chair: both prior conditions satisfied; approved
for banking). Bank with the P1 commit once D-030 is signed.

EXP-003 is designed now. EXP-002 now has a recorded NULL. Chair 2026-08-25
deferred implementation until after M0/M1 review (P5 then P6). It cannot
revive fuel, authorize M4, or inherit an interaction claim. First proxy is Hyperliquid published impact prices at the
venue-published impact notional. Engineer may inspect schema; Engineer may
not choose the match design. Unstable published notional → probe returns
to CTO, no score.

Frozen match: unique taker/crossed fills deduplicated by `tid`, **only
the immediately following epoch-aligned 60s bucket `(T, T+60s]`**, no
forward search, eligibility `[0.5×, 2×]`, unmatched = missing, backstop
excluded. Aggressive buy uses published impact **ask**; aggressive sell
uses impact **bid**. Fuel distance bands are not EXP-003 primary cells.
Trailing realized impact is a later independent candidate. Details in
`docs/briefs/2026-08-25-p1-impact-construct.md` v3.

## D-032 — Evaluation unit freeze (P5)

**Accepted** (2026-08-25, Chair: swap P5 ahead of P4; authorize P5 only).
Details: `docs/briefs/2026-08-25-p5-eval-unit.md`.

**Correction (2026-08-25, Codex CTO seat, before any EXP-004 fit or score).**
The first text incorrectly made pure-direction positive clusters the evaluation
population. That future-conditioned event-only sample has no non-events and cannot
estimate prospective probability, calibration, or alert precision. It is
superseded, not retained as an alternative.

The prospective sampling frame is the D-022 index at fixed UTC-hour interval-end
timestamps. Direction is a categorical first cause (`UP`, `DOWN`, `NONE`; same-bar
`AMBIGUOUS` and future data gaps unscored), with the opposite barrier an explicit
competing event. Pure and mixed clusters group positive outcomes after sampling;
they never select rows. Scoreable hourly states carry base weight 1 for probability
metrics; alert episodes carry weight 1 for precision; direction x horizon event
clusters carry weight 1 for recall and lead time. One family-wide UTC-week block
bootstrap keeps all linked rows and episode/cluster contributions together.

The v0 precondition rule is frozen causally: require
`abs(log(P_T/P_{T-15m})) < log(1.005)` on exact D-022 endpoints. No forward fill;
the same risk set applies to fixed and twin families. D-023 periods and four-hour
boundary purge/embargo remain binding.

The twin remains `x_T = kappa * sigma_T`, with causal 24h realized volatility and
`kappa = 0.02 / median(sigma_T)` locked to six decimals on eligible D-023
development hourly timestamps before outcomes. Primary M0/M1 cells remain
`{1h,4h} x {up,down}`; the twin is a required companion family.

Primary probability lift is equal-weight four-cell relative Brier skill over the
preceding rung, accompanied by calibration, precision at a development-frozen 1%
alert-time budget, event-cluster recall, and median lead time. Spearman on
event-only rows is not an evaluation metric. Exact outcome, missingness, materiality,
and episode rules are in the corrected brief.

This closes the D-026 estimator choice, prospective evaluation population,
competing-risk semantics, precondition impulse exclusion, dependence/weighting,
and evaluation yardstick. EXP-004 remains PLANNED and unscored. No P6, P4, or
EXP-003 work is authorized by the correction.

## D-033 — EXP-004 implementation contract frozen; M1 as-of evidence blocked

**Accepted** (2026-08-25, Codex CTO seat; contract and availability commission
only). Details:
`docs/briefs/2026-08-25-p6-implementation-freeze.md` and
`reports/exp004/m1_availability.*`.

M0 is exactly seven causal columns on D-022: trailing 4h signed log return,
trailing 4h log high/low range, D-032 24h realized volatility, and sine/cosine
controls for UTC hour and weekday. M1 adds exactly four generic columns, with no
substitution: Binance USD-M OI-notional log level, 24h realized funding sum,
same-venue USD-M/spot log-close premium, and taker-flow residual-variance
compression reconstructed from USD-M kline quote-volume fields. The latter uses
the same five-minute buy/sell-flow construct as the motivating study, with one
frozen 8h detrend and 2h variance window rather than a parameter sweep
(https://arxiv.org/abs/2607.27070). The companion study describes 25–70% OI
clearing as an in-cascade signature, so EXP-004 uses a precondition OI level and
does not leak OI collapse into a predictor
(https://arxiv.org/abs/2608.03616).

The D-019 source audit verified all 1,962 manifest entries and on-disk hashes:
79 monthly spot kline, 79 monthly USD-M kline, 79 monthly funding, and 1,725
daily metrics archives. It also banks their exact schemas, mixed spot ms/us
timestamp seam, raw close-time anomalies, funding millisecond jitter, metrics
gaps/off-grid rows, two conflicting duplicate metrics timestamps, and
same-interval spot/perpetual coverage. Those facts freeze explicit unit
normalization, no-flooring, conflict-as-missing, and complete-case rules.

Raw completeness is not point-in-time publication evidence. Kline interval
completion is accepted under D-017 for premium and taker flow because it is the
same causal exchange-bar convention already required for Oracle price inputs.
The metrics and funding archives expose `create_time` / `calc_time` and bulk
retrieval time, but no historical publication/receive timestamp or authoritative
latency bound. A made-up safety delay would not cure that defect. OI and funding
therefore fail the publication-evidence gate, and the complete M1 rung is
`BLOCKED_ASOF` before any fit. Do not shrink M1, substitute Hyperliquid or a
parked fuel proxy, acquire a new family inside this commission, or treat this as
a predictive verdict. A later owner may supply point-in-time evidence or
authorize M0 alone.

The future estimator, if separately authorized, is one deterministic
baseline-category multinomial logistic regression per rung x horizon x label
family, `NONE` reference, development-only standardization, fixed ridge
coefficient `1e-4`, and exact common support for `M0_COMMON` versus M1. No
hyperparameter search or OOS refit is allowed. D-032 Brier/calibration and alert
metrics are completed by all-period/all-family mechanical PASS gates, stable
adverse FAIL gates, and NULL otherwise. Volatility, UTC session, and positive
cluster morphology are non-gating descriptive slices. EXP-004 records
`NEWS_NOT_AVAILABLE` for M0/M1 because no frozen point-in-time corpus exists;
D-015 still requires a news protocol before M2+.

No feature builder, risk-set implementation, estimator, fit, threshold, score,
or validation/test effect was produced. EXP-004 remains PLANNED with blank
Result/Verdict. P6 and P4 / EXP-003 remain unstarted.

## D-034 — EXP-004 M0-only one-shot execution authorized

**Accepted** (2026-08-25, Chair direct commission). This authorization is
strictly the frozen M0 rung under D-032/D-033. It supersedes the historical P6
stop line only for M0 and does not authorize M1, M2+, a partial M1, replacement
sources, publication-lag invention, EXP-003/P4, or any feature or threshold
change.

The implementation must first pass focused and synthetic tests plus a
development-only run that cannot construct or score a timestamp at or after
2024-01-01. A clean immutable implementation commit is then the pre-OOS SHA.
The OOS runner must reject any other or dirty checkout, consume one local
one-shot receipt before constructing OOS outcomes, fit only the deterministic
development estimator, apply its scaler/climatology/thresholds unchanged, and
report validation, 2025, and 2026-01..07 separately for fixed and twin. The
D-033 PASS/FAIL/NULL/BLOCKED rule is mechanical; no post-inspection retuning or
slice rescue is permitted. M1 stays `BLOCKED_ASOF` and unimplemented.

At this decision point no validation or test effect has been constructed or
inspected. Result and verdict remain blank until the exact-SHA run is banked.

## D-035 — EXP-004 M0 closes NULL; stop at the rung boundary

**Accepted** (2026-08-25, mechanical D-033 disposition after the D-034 one-shot
commission). Evidence:
`reports/exp004/m0_result.{json,md}`, `m0_frozen_state.json`, and
`m0_result.provenance.json`.

The development-only firewall passed before the immutable pre-OOS SHA
`680f2af101f88b55e761945390f6da020c9e9a71` was sealed. The exact clean-SHA run
then consumed one local receipt and reverified 11,770 D-022 inputs. It is valid.
M0 family relative Brier skill is positive and at least 1% for fixed and twin
in validation, test-2025, and test-2026-01..07. That does not satisfy PASS:
the frozen rule requires every primary cell's alert precision, cluster recall,
lead, and 30-cluster floor in every period and both label families. Cluster
recall is below 10% in every cell, with additional precision, lead, and count
misses. The adverse all-period/all-family `<= -1%` skill rule is also false.
The only permitted disposition is therefore **NULL**.

No threshold, scaler, model, support, slice, or metric was changed after OOS
inspection. There is no pooled, fixed-only, or descriptive-slice rescue. M1
remains `BLOCKED_ASOF` before fit; this result does not authorize a partial M1,
M2+, EXP-003/P4, a new feature, or a rerun. Return to Chair review.

## D-036 — EXP-003/P4 blocks at the pre-effect source gate

**Accepted** (2026-08-25, CTO mechanical disposition under the direct P4
commission). Contract:
`docs/briefs/2026-08-25-p1-impact-construct.md` v4, commit
`8e23b80366c9414d754afd84dbbf49e13c4e0983`. Evidence:
`reports/exp003/source_readiness.*`, banked at
`23c838e5721bdde90b4797fda72b51ec9950fa38`.

The raw `asset_ctxs` schema is stable and names exact mark, impact-bid, and
impact-ask fields, but it carries neither impact notional/source-semantics
version nor receive/publication time. Hyperliquid's available official contract
specifications document 20,000 USDC for BTC/ETH from the earliest authoritative
capture found (2024-03-24). Fixed, effect-blind walks of the venue's own L2
archive instead reproduce an approximately 5,000-USDC regime through
2023-05-30 and 20,000 USDC after a transition in
`(2023-05-31T01:32:00Z, 2023-05-31T01:32:22Z]`. The early regime has no
authoritative versioned specification. Separately, the archive and live API do
not establish that a CSV row stamped `T` was publicly knowable no later than
`T`; archive upload occurs later and is not market-time provenance.

Both defects independently fail the frozen one-stable-authoritative-notional and
causal-as-of gates. EXP-003 is therefore **BLOCKED_SOURCE before effects**. The
next-60-second eligibility census, VWAP/slippage construction, correlation,
bootstrap, implementation SHA, and one-shot receipt are all `NOT_RUN`. No
later-only history restriction, inferred notional schedule, alternate timestamp,
order size, window, or proxy may rescue this EXP. A materially revised source
contract requires Chair review and a new decision; this block does not revive
fuel, authorize M3/M4, or promote trailing realized impact.

## D-037 — Exact D-033 flow compression receives one standalone replication

**Accepted** (2026-08-25, direct EXP-005 commission; before label/effect
inspection). EXP-005 asks one bounded question: does the exact D-033
`flow_compression_T` precursor add prospective OOS information and useful event
selectivity beyond the seven-column M0 on identical support? The construct is
anchored to the taker buy/sell-flow variance-compression precursor reported in
the motivating cascade study (https://arxiv.org/abs/2607.27070); Oracle's
pre-frozen 8h detrend and 2h variance window are an operational replication on
the broader D-032 +/-2% population, not a new parameter search.

The comparison is `M0_COMMON` versus `M0_FLOW`, fitted separately by horizon and
label family. `M0_COMMON` is the exact seven D-033 M0 columns on flow-complete
rows; `M0_FLOW` adds only the exact D-033 flow-compression column. Both rungs
must fit and score on byte-identical timestamp support. The estimator, splits,
purge, labels, weights, bootstrap, alert mechanics, slices, and integrity gates
remain D-032/D-033 unchanged. Long-support banked M0 is context only.

Checkpoint A is pre-effect. It freezes the EXP-005 brief and runs a D-019
source audit of the Binance USD-M one-minute klines, exact five-minute blocks,
and hourly common support without constructing or inspecting any label
relationship. Each period requires at least 90% flow availability, at least 85%
`M0_FLOW` joint availability, and no zero-coverage calendar month. A causal,
provenance, or source failure banks `BLOCKED_SOURCE`; valid but sub-floor
coverage banks `NULL_COVERAGE`; either stops the EXP before effects.

Only a cleared Checkpoint A authorizes the immutable implementation and one
development-only firewall specified in
`docs/briefs/2026-08-25-exp005-flow-compression-replication.md`. A clean pre-OOS
implementation SHA is required before one exact-SHA OOS execution consumes one
local receipt. PASS/FAIL/NULL/BLOCKED is mechanical under that brief. A PASS
validates only this standalone comparator; it does not unblock M1, authorize
M2+, waive D-029's later untouched confirmation, or support a definitive
predictive headline. No alternate flow measure, window, lag, transform,
threshold, rerun, or post-hoc rescue is authorized.

**Checkpoint A clearance (2026-08-25; still pre-effect).** The D-019 audit at
implementation SHA `079a0e0ba8e856a679267bac38ecca08359b2bb0`, evidence commit
`79851be`, reverified all 79 selected USD-M one-minute archives and all 11,770
D-022 source inputs. Flow coverage was 99.82% development, 99.83% validation,
99.77% test-2025, and 100% test-2026-01..07. Seven-M0-plus-flow joint coverage
was 99.58%, 99.83%, 99.77%, and 100%, respectively, with no zero-coverage
month. Schema, hashes, exact block membership, interval-end causality, T-5m,
duplicate/conflict handling, and paired support identifiers all clear. The
audit constructed no labels, outcomes, fits, scores, or effects. The frozen
Checkpoint A disposition is `CLEARED_CHECKPOINT_A`, so Checkpoint B is
authorized unchanged.

**Final disposition (2026-08-25).** The real development firewall at candidate
SHA `3e7190293bbafc952d1280de9c2b58bde793f335` admitted only timestamps,
passages, and clusters strictly before `2024-01-01T00:00:00Z`, preserved D-032
`kappa=0.771724`, froze four development support identifiers and eight fresh
models, and constructed or froze no OOS score support. Its external envelope
SHA-256 was `dbae564be6a2a8533c26080366bdbc9e73c543d05c1070bcb083ddc5fddc580a`;
the frozen state SHA-256 was
`317bdc2926b35163f2da10a3ecb12d09e5ec8e87e87b3dbc363e0de9ffa1e8c2`.

Empty seal commit `7fa0709011f451d0fc5ef95b5f4b5e7baf8152ed` retained the exact candidate
tree. Its one-shot run consumed the experiment-wide receipt once, loaded the
frozen development state without refit, and completed valid. Evidence commit
`7ab09aa62b4392c61aa93d40752ca1ec3bd86efb` records family relative Brier
skill for fixed/twin as `0.1785% / -0.0040%` in validation, `0.2180% / 0.0309%`
in test-2025, and `0.1346% / -0.0305%` in test-2026-01..07. All six family
skills miss the `+1%` PASS floor; the all-six `<=-1%` FAIL condition is also
false. Multiple primary cells independently miss recall, minimum-cluster, and
other actionability gates. The only mechanical disposition is therefore
**NULL**. Exact D-033 flow compression is parked as a standalone comparator;
there is no alternate window, transform, threshold, or rerun. M1 remains
complete and `BLOCKED_ASOF`, and no M2+ or other rung is authorized.

## Open decisions

- Raw and derived data roots (host layout accepted in D-010; naming/manifest
  conventions for derived layers pending).
- Point-in-time publication evidence or a replacement source decision for the
  required EXP-004 OI and funding families (D-033 blocks M1; no acquisition is
  authorized).
- Point-in-time historical source selection for any future fuel challenger.
- Authoritative versioned impact-notional history and row-level as-of semantics
  for any future quoted-impact attempt. Narrowing EXP-003 to the later regime is
  a contract change and is not authorized by D-036.
- Concrete news-tagging protocol before M2+ (source list, tag taxonomy, freeze
  procedure); EXP-004 M0/M1 records `NEWS_NOT_AVAILABLE`.
