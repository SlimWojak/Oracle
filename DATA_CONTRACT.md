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

### Canonical decision timestamp (D-017)

A label anchored on a bar's close is knowable only at interval end. The
canonical decision timestamp for bar-anchored labels is therefore the interval
end (`open_time + 60s` for Binance 1m klines). Feature as-of joins, embargoes,
and split boundaries all operate on interval-end decision timestamps, never the
raw interval-start stamp.

### Known convention traps (binding)

- Binance futures metrics dumps stamp the interval **end**, while Binance kline
  timestamps mark the interval **start**. Joining them naively shifts flow one
  bar ahead of returns and has produced published spurious-causality results.
  A -5 minute realignment of the metrics feed is required and must be asserted
  by a lag-correlation audit in the normalization layer.
- The D-033 audit found that Binance spot monthly klines switch raw epoch units
  from milliseconds to microseconds at 2025-01, while USD-M klines remain in
  milliseconds. Normalize units explicitly before joins. Preserve anomalous raw
  `close_time` values; do not rewrite them to the nominal interval end.
- Binance funding `calc_time` can occur milliseconds after the nominal eight-hour
  boundary, and Binance metrics can occur seconds off the five-minute grid.
  Causal joins use raw timestamps without flooring. Differing duplicate metrics
  timestamps are conflicts/missing for EXP-004, never last-file-wins revisions.
- Binance metrics and funding bulk archives do not provide historical
  publication/receive time. Their source/event timestamps and a later bulk
  retrieval timestamp do not, by themselves, clear the feature as-of gate
  (D-033). Do not manufacture causality with an arbitrary delay.
- The Hyperliquid fill log attaches the liquidation object to both legs of each
  forced trade. All liquidation totals must be deduplicated by the
  liquidated-user leg or they double-count.
- Hyperliquid `asset_ctxs` CSV rows carry a point-snapshot `time`, but no
  receive/publication timestamp, block number, sequence, impact-notional field,
  or source-semantics version. Some early rows are off the UTC-minute grid and
  flooring creates conflicting quote collisions. D-036 also finds source-only
  evidence of an early approximately 5,000-USDC impact regime followed by
  20,000 USDC, while the available authoritative specification is not versioned
  over the full history. Never floor, forward-fill, infer a historical notional
  schedule, or claim public availability at raw `time` without new source
  evidence.
- The Hyperliquid fill log begins 2025-05-25. No observed fuel surface exists
  before that date; earlier periods may only use inferred or vendor challengers.

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

## Run provenance (D-019)

Every data-host run that produces committed evidence records the repository
commit SHA, configuration hash, input manifest identifiers, UTC execution
time, and output content hashes.

## Prohibited practices

- Reconstructing historical point-in-time heatmaps from a current vendor view.
- Using revised data without an as-of publication record.
- Treating sampled liquidation streams as complete liquidation tape.
- Treating account-count long/short ratios as dollar exposure.
- Random train/test splits across market time.
- Imputing across cascade-period feed loss without an explicit sensitivity analysis.
