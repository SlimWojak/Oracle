# Oracle

Oracle is a standalone research laboratory for studying whether the interaction of
directional leverage, market impact susceptibility, and signed ignition contains
out-of-sample information about sharp BTC market moves.

The initial target is deliberately narrow:

> Does direction-specific fuel interact with poor absorption to raise the
> probability of a +/-2% BTC first passage within one or four hours, and does
> aligned ignition add incremental timing information?

Oracle is a study, not an indicator, trading system, execution service, or data
platform. Negative results are first-class outputs.

## Research sequence

1. Build a consolidated BTC event catalogue.
2. Establish causal, point-in-time fuel challengers.
3. Establish deliberately simple impact-susceptibility proxies.
4. Add signed ignition only after vulnerability tests are frozen.
5. Evaluate each layer incrementally out of sample.

The core state language is:

`DORMANT -> LOADED -> ARMED -> IGNITING -> PROPAGATING -> EXHAUSTED`

Liquidations and open-interest clearing normally describe propagation, not
prediction.

## Repository map

```text
AGENTS.md                 instructions and fences for coding agents
THESIS.md                 durable research thesis and open questions
RESEARCH_CONTRACT.md      v0 hypotheses, exclusions, validation and kill rules
DATA_CONTRACT.md          causal timing and data lineage requirements
EXPERIMENT_LEDGER.md      append-only experiment records
configs/v0.yaml           frozen initial study configuration
docs/HANDOVER.md          CTO seat orientation (abstract); see HANDOVER_LOCAL.md locally
docs/DECISIONS.md         accepted architectural/research decisions
src/oracle_research/      deterministic research primitives
scripts/                  report-producing runners (EXP-000 catalogue, EXP-001 census)
tests/                    focused tests for those primitives
notebooks/                disposable exploration only; never canonical logic
reports/                  generated evidence reports; no raw data
reports/exp000/           EXP-000 catalogue, clusters, sensitivity
reports/exp001/           EXP-001 stratification census and reconstruction
```

## Setup

Oracle targets Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,hyperliquid]'
python -m unittest discover
ruff check .
```

Install analytical-store dependencies only when building or querying Parquet:

```bash
python -m pip install -e '.[dev,hyperliquid,analytics]'
```

## Data boundary

Raw data lives outside this repository and is immutable. Local paths, credentials,
vendor payloads, and generated datasets must not be committed. Derived datasets
must be reproducible from a manifest recording source, retrieval time, exchange
timestamp semantics, transformation version, and content hash.

### Hyperliquid fills Parquet store (D-012)

The one-time builder materializes the primary all-fills table outside git:

```bash
python scripts/build_hl_btc_liquidations.py \
  --data-root /home/a8ra_dgx/oracle-data \
  --overwrite
```

It writes Parquet under
`{data_root}/derived/hyperliquid/fills/v1/all_fills` and a rebuild manifest
beside that table. Verify hard parity against the banked EXP-001 census without
re-reading LZ4:

```bash
python scripts/run_hl_parquet_census_parity.py \
  --data-root /home/a8ra_dgx/oracle-data
```

The parity gate emits `reports/infra_hl_parquet_v1/parity.{json,md}` plus a
D-019 provenance sidecar and exits non-zero if data is missing or any aggregate
mismatches.

## Current status

Active sequence: [`docs/glide_path.md`](docs/glide_path.md) (v1). P0, P1, P2,
P3, and P5 are **BANKED**. P3 / EXP-002 closed **NULL** and
`cex_oi_cohort_v0` is parked. P5 banks the corrected prospective D-032
evaluation freeze; EXP-004 remains **PLANNED and unscored**. P4 / EXP-003 is
deferred. D-033 banks the exact M0/M1 implementation contract and label-blind
source audit, but P6 implementation is not authorized.


EXP-000 closed **PASS** (2026-08-24): D-022 consolidated index labels, D-023
chronological splits, per-cluster inventory in `reports/exp000/`.

EXP-001 closed **FAIL** (2026-08-24): HL-observed fuel demoted per D-018. Phase 1
tractable share 39%; Phase 2 reconstruction accuracy 8%.

P5 closed (2026-08-25) without fitting or scoring. The evaluation population is
now a causal UTC-hour D-022 risk set containing events and non-events, with
categorical competing-risk outcomes, a frozen precondition impulse exclusion,
explicit timestamp/episode/cluster weights, the fixed ±2% label plus causal
volatility twin, and Brier/calibration/alert metrics. The event-cluster catalogue
groups positive outcomes but is not the sampling frame. Challenger-history
inventory now derives from `reports/exp000/index_clusters.json` with D-019
provenance.

The M1 archive inventory is complete and checksum-verified, but source
completeness is not publication-time provenance. Binance metrics OI and funding
history do not carry historical publication/receive timestamps or an
authoritative latency bound, so D-033 marks the required complete M1 rung
`BLOCKED_ASOF` before fitting. Premium and taker-flow candidates clear the
existing D-017 kline interval-end convention. No feature builder, estimator,
fit, score, or validation/test effect was produced. The next owner decision is
point-in-time evidence/replacement sources for OI and funding, or a separately
authorized M0-only implementation commission.

Implemented primitives include consolidated-index construction, venue-replication
gate, Kraken trades-to-bars, Hyperliquid fill normalization (`hyperliquid_fills`,
`hl_liquidations`, optional `[hyperliquid]` deps for lz4), and EXP-001 census/
reconstruction runners. Raw data acquisition is on the external data host
(`dexter`).
