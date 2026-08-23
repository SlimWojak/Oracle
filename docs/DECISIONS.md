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

## Open decisions

- Raw and derived data roots (host layout accepted in D-010; naming/manifest
  conventions for derived layers pending).
- Point-in-time historical source selection for fuel challengers.
- Volatility-normalized barrier estimator.
- Precondition-clock impulse exclusion.
- Normalized book-walk sizing rule.
- Initial chronological split boundaries.
- Training/scoring weight policy for large clusters (thousands of anchor votes
  vs capped weight vs one episode-level contribution).
- Concrete news-tagging protocol (source list, tag taxonomy, freeze procedure).

