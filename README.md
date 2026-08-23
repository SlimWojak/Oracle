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
docs/DECISIONS.md         accepted architectural/research decisions
src/oracle_research/      deterministic research primitives
tests/                    focused tests for those primitives
notebooks/                disposable exploration only; never canonical logic
reports/                  generated evidence reports; no raw data
```

## Setup

Oracle targets Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m unittest discover
ruff check .
```

## Data boundary

Raw data lives outside this repository and is immutable. Local paths, credentials,
vendor payloads, and generated datasets must not be committed. Derived datasets
must be reproducible from a manifest recording source, retrieval time, exchange
timestamp semantics, transformation version, and content hash.

## Current status

The repository is at research-contract stage. The first implemented primitive is
bar-aware first-passage labelling, including explicit ambiguity when both barriers
are touched within one bar and event ordering cannot be recovered.
