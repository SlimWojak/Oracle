# P1 — EXP-002 fuel construct (v5, banked)

CTO 2026-08-25. Chair four-cell ruling. **Accepted with D-030.**
This is a pre-outcome feasibility correction: no fuel values and no HL
liquidation mass were used to choose the family.

P2 is authorized from this freeze. Engineer implements this brief only.

## Claim (narrow)

CEX-inferred **directional fuel proxy**, not a liquidation topology.
Challenger `cex_oi_cohort_v0` uses causal entry-price cohort memory of
signed Binance UM **contract-quantity** changes, side-split by top-trader
position LSR, valued at P_T. It is hypothesized to rank subsequent
Hyperliquid **book-hitting** BTC liquidation notional when the named
**adverse-entry-distance** band is **far-edge** traversed.

PASS makes the challenger **M2-eligible only for the four primary 4h
cells**. It validates neither 1h nor `[2, 4%)`. FAIL kills this
measurement path, not the mechanism. NULL parks. One cross-venue miss:
*fails the observable construct gate; cause unresolved.*

If feature or target integrity later reduces any primary cell below its
coverage floor, the verdict is **NULL**, not another redesign.

Limitation (every table): every futures contract has both a long and a
short. LSR only reweights the same contract stock. This is a
**top-trader-position-weighted directional proxy**, not venue-wide
long/short gross exposure.

## Primary family (frozen)

Exactly four cells:

`4h × {up, down} × {(0, 1%), [1, 2%)}`

Coverage floors, **no further relaxation**:

- construct-dev ≥ 10 eligible clusters per cell
- construct-val ≥ 15 eligible clusters per cell

`F` is the equal-weight mean of
`(Spearman_challenger − Spearman_OI_only)` over these four cells.

1h and `[2, 4%)` are **parked**. They are excluded from `F` and from
design decisions. Any later descriptive output on them is explicitly
**non-confirmatory**.

Path-only census: `reports/p1_eligibility_census.json` (+ D-019 sidecar).
Status SPARSE on the old 12-cell family; the four primary cells meet the
floors above (dev down 22–23, dev up 12, val down 23, val up 28).

## Source

Binance Vision `um/daily/metrics/BTCUSDT`, 5-minute `create_time`
(verified 288 rows/day).

| Field | Use |
|---|---|
| `create_time` | as-of; DATA_CONTRACT interval-end + kline realignment |
| `sum_open_interest` | contract quantity Q_t (cohort accounting) |
| `sum_open_interest_value` | OI-only USD baseline + unit check (never Δ-cohorts) |
| `sum_toptrader_long_short_ratio` | top-trader **position** LSR |

Count-ratio fields forbidden. `sum_taker_long_short_vol_ratio` unused.
LSR missing / non-positive / not a position ratio → NULL.

## Side stocks

```
Q_t = sum_open_interest[t]
L_t = Q_t × LSR_t / (1 + LSR_t)
S_t = Q_t × 1     / (1 + LSR_t)
ΔL_t = L_t − L_{t−1}
ΔS_t = S_t − S_{t−1}
```

Side stocks move when Q changes **or** LSR changes at flat Q. Gap > 15
minutes: skip (no invented Δ).

## Opening stock: unallocated bucket

At the first usable metrics row in 2021-12:

```
unallocated_long  = L_0
unallocated_short = S_0
priced cohorts    = empty
```

Unallocated buckets have **no entry price** and **never** contribute to
a fuel band. Burn-in through 2025-05-24 23:59 UTC. No synthetic opening
cohort at an invented price.

Each 5-minute update, per side:

- `Δ > 0`: add a priced cohort of quantity Δ with `entry_price = P_t`.
- `Δ < 0`: reduce **unallocated + priced cohorts pro rata** by |Δ|;
  clip the side at zero. No cross-side transfer.

Conservation (else NULL):

```
unallocated_side + sum(priced cohort qty) == inferred side stock
```

relative residual ≤ 1e-6 after burn-in, except at explicit clips.

## Adverse-entry-distance bands

```
long_adverse_distance  = max(entry_price / P_T − 1, 0)
short_adverse_distance = max(P_T / entry_price − 1, 0)
```

Profitable cohorts map to 0 and **must not** enter `(0, 1%)`.
Primary bands: **`(0, 1%)`**, **`[1, 2%)`**. `[2, 4%)` is parked.
Compare within band. These are not estimated liq-price bands.

## Target path distance (fills)

```
downside fill distance = 1 − fill_px / P_T
upside fill distance   = fill_px / P_T − 1
```

Downside dirs: Close Long / Liquidated Isolated Long / Liquidated Cross
Long. Upside: Short counterparts. ADL out. Backstop never pooled.

## Traversal: far edge

| Band | Downside far edge | Upside far edge |
|---|---|---|
| `(0, 1%)` | P_T × 0.99 | P_T × 1.01 |
| `[1, 2%)` | P_T × 0.98 | P_T × 1.02 |

Eligible only if the index path on `(T, T+14400s]` reaches that far edge.

## Inferential unit (cluster, not minute)

One row per **pure-direction 4h cluster × direction × band**.

- Use the EXP-000 **4h** cluster inventory only.
- Mixed clusters count toward **neither** direction.
- Candidate T: 1-minute decision timestamps in
  `[cluster.start_timestamp, cluster.end_timestamp]`.
- Keep the **earliest eligible T**. If none, the cluster is ineligible
  for that band.
- Feature, target, Spearman, terciles, and F use these cluster rows.
- The cluster is assigned to the **UTC week of `cluster.start`**
  (Monday 00:00).

**Bootstrap:** one **family-wide** weekly draw. A drawn week carries
every selected cluster’s **linked rows across both bands**. No
independent cell resampling. Never split one cluster across weeks.

```
rng = numpy.random.default_rng(20250825)
B = 1000
draw weeks with replacement
F* = F on all four cell-rows belonging to the drawn clusters
SE = sample_std(F*, ddof=1)
floor = max(0.10, 2 * SE)   # six decimals, construct-dev only
```

If any primary cell is below its window floor or any Spearman is
undefined on construct-dev: do not lock; P3 cannot PASS.

## Shape and stability gates

**Flipped hard:** terciles on cluster rows (≥5 rows/tercile or
integrity NULL). `m3 < 0.8 × m1` when `m1 > 0`, else `m3 < m1`.

Shape: `m3 ≥ m1` in **≥ 3 of 4** cells, and **zero** hard flips.

Stability blocks (replace monthly): **Sep–Oct 2025** and **Nov–Dec 2025**.
Each block must have ≥ 10 eligible clusters per primary cell, a defined
F, and **positive** challenger-minus-OI F. A block that fails integrity
is a failed block, not dropped.

## Baselines

1. OI-only USD: `sum_open_interest_value × side_share` at the chosen T.
2. Trailing-price-path over 4h.
3. Negative control `cex_oi_band_static` weights `(2/3, 2/9, 1/9)` —
   the unused 4% weight is ignored for the two-band primary (renormalize
   the first two midpoints `{0.5%, 1.5%}` to `(0.75, 0.25)`).

Must beat (1) and (2) on F.

## PASS / FAIL / NULL

PASS (all, construct-val): every cell ≥ 15; Spearmans defined; F ≥ floor
and family-wide week-block CI95 excludes 0; same vs trailing-path;
shape gate; both Sep–Oct and Nov–Dec blocks pass; static control F does
not exceed challenger F.

FAIL: integrity holds and a PASS clause fails.

NULL: any primary cell below its floor after feature/target construction;
LSR audit fail; tape coverage fail; no floor locked; conservation break.

Alert budget, lead time, and probability lift are not used here.

## Firewall (D-029 accepted)

Burn-in first usable 2021-12 row .. 2025-05-24 (unscored).
Construct-dev 2025-05-25 .. 2025-08-31.
Construct-val 2025-09-01 .. 2025-12-31.
First look 2026-01-01 .. 2026-07-31.
Second confirmation 2026-08-01 .. 2026-12-31.

## P2 materialization (named now)

- 5-minute side-quantity cohort state (unallocated + priced; spill ok).
- Per cluster-row: fuel, OI-only, path baseline, book-hitting vs
  backstop USD by fill-distance band vs P_T on `(T, T+4h]`.
- Far-edge traversal flag per (cluster, direction, band).

Do not compact the 82,512 fill parts. Do not build generic query infra.
Do not run P3 scoring in P2.

## Anti-goals

- OI-value Δ as cohort flow.
- Inventing an opening entry price.
- Minute-level Spearman dressed with a cluster count.
- Reintroducing 1h or `[2, 4%)` into F or design.
- Independent per-cell bootstrap.
- Another family redesign if a cell later goes thin (NULL instead).
