# Data contract

## Principle

Every row used by Oracle must represent what was knowable at its decision timestamp.
Source timestamps are not assumed to share semantics.

## Required raw metadata

Where provided by the source, retain:

- `source`
- `venue`
- `instrument`
- `event_type`
- `exchange_timestamp`
- `receive_timestamp`
- `interval_start`
- `interval_end`
- `sequence_id`
- `source_timezone`
- `retrieved_at`
- `schema_version`
- `source_semantics_version`

Never overwrite an exchange timestamp with a local receipt timestamp or vice versa.

## Interval semantics

Every interval field must declare whether its timestamp denotes:

- interval open;
- interval close;
- event time;
- publication time;
- receipt time.

Mixed-source alignment requires an explicit audit. A high contemporaneous
correlation is not sufficient evidence that interval conventions align.

## Storage layers

### Raw

- External to the repository.
- Immutable and append-only.
- Exact vendor/exchange payload preserved when licensing permits.
- Partitioned without changing event content.

### Normalized

- Rebuildable from raw data.
- Canonical units and instrument identifiers.
- Transformation version and input hashes recorded.
- No forward fill across feed gaps unless the specific field contract permits it.

### Features

- Every feature has a named lookback and as-of rule.
- Feature availability uses publication/receipt time, not only economic event time.
- Missingness and source outages remain observable.
- Vendor-derived features retain vendor/model identity.

### Labels

- Built only from future prices relative to the feature snapshot.
- Stored separately from features.
- Never joined into a feature table before the frozen split contract is applied.

## Manifest requirements

Each dataset used by an experiment records:

- source and coverage;
- retrieval time;
- raw content hashes or immutable object identifiers;
- normalization commit/version;
- known gaps and outages;
- timezone and timestamp conventions;
- symbol mapping;
- licensing/reproducibility boundary.

## Prohibited practices

- Reconstructing historical point-in-time heatmaps from a current vendor view.
- Using revised data without an as-of publication record.
- Treating sampled liquidation streams as complete liquidation tape.
- Treating account-count long/short ratios as dollar exposure.
- Random train/test splits across market time.
- Imputing across cascade-period feed loss without an explicit sensitivity analysis.

