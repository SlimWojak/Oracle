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

EXP-000 closed **PASS** (2026-08-24): D-022 consolidated index labels, D-023
chronological splits, per-cluster inventory in `reports/exp000/`.

EXP-001 closed **FAIL** (2026-08-24): HL-observed fuel demoted per D-018. Phase 1
tractable share 39%; Phase 2 reconstruction accuracy 8%. Construct validation and
normalization layer are next.

Implemented primitives include consolidated-index construction, venue-replication
gate, Kraken trades-to-bars, Hyperliquid fill normalization (`hyperliquid_fills`,
`hl_liquidations`, optional `[hyperliquid]` deps for lz4), and EXP-001 census/
reconstruction runners. Raw data acquisition is on the external data host
(`dexter`).
