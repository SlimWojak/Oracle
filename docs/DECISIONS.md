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
mechanical, well-specified work is delegated to lighter Cursor-native models.
Contract documents, experiment design, and verdicts are never delegated. Details
in `AGENTS.md`.

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

## Open decisions

- Raw and derived data roots (host layout accepted in D-010; naming/manifest
  conventions for derived layers pending).
- Point-in-time historical source selection for fuel challengers.
- Volatility-normalized barrier **estimator** (requirement and finding-blocker locked in D-026; estimator choice still open).
- Precondition-clock impulse exclusion.
- Normalized book-walk sizing rule.
- Training/scoring weight policy for large clusters (thousands of anchor votes
  vs capped weight vs one episode-level contribution).
- Concrete news-tagging protocol (source list, tag taxonomy, freeze procedure).

