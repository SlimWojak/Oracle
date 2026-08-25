"""Paired common-support population mechanics for EXP-005.

The input population is the already-frozen D-032/D-033 ``PopulationResult``.
This module only intersects that population with one caller-supplied finite
``flow_compression_T`` mask.  It never changes an ``M0RiskRow`` and it applies
the same ordered timestamp support to ``M0_COMMON`` and ``M0_FLOW``.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from oracle_research.exp004_m0_population import (
    HORIZONS,
    LABEL_FAMILIES,
    M0_COLUMNS,
    M0RiskRow,
    PopulationResult,
    support_identifier,
)
from oracle_research.exp005_flow import M0_FLOW_COLUMNS

RUNGS = ("M0_COMMON", "M0_FLOW")


class BlockedSupportError(RuntimeError):
    """Raised when the exact paired timestamp support is not identical."""


def assert_ordered_support_identity(
    m0_common_timestamps: Sequence[int],
    m0_flow_timestamps: Sequence[int],
    *,
    context: str = "",
) -> tuple[int, ...]:
    """Return the shared support or raise the frozen ``BLOCKED_SUPPORT`` error."""

    common = tuple(int(value) for value in m0_common_timestamps)
    flow = tuple(int(value) for value in m0_flow_timestamps)
    suffix = f" for {context}" if context else ""
    if common != flow:
        raise BlockedSupportError(f"BLOCKED_SUPPORT: ordered rung support mismatch{suffix}")
    if any(right <= left for left, right in zip(common, common[1:], strict=False)):
        raise BlockedSupportError(
            f"BLOCKED_SUPPORT: timestamp support is not strictly increasing{suffix}"
        )
    return common


@dataclass(frozen=True, slots=True)
class FlowRiskRow:
    """A non-mutating view of one base row with the sole challenger feature."""

    base_row: M0RiskRow
    flow_compression_T: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.flow_compression_T):
            raise ValueError("flow_compression_T must be finite")

    @property
    def timestamp(self) -> int:
        return self.base_row.timestamp

    @property
    def period(self) -> str:
        return self.base_row.period

    @property
    def m0_common_features(self) -> tuple[float, ...]:
        features = self.base_row.features
        if features is None or len(features) != len(M0_COLUMNS):
            raise BlockedSupportError("BLOCKED_SUPPORT: paired row has incomplete M0 features")
        if not all(math.isfinite(value) for value in features):
            raise BlockedSupportError("BLOCKED_SUPPORT: paired row has nonfinite M0 features")
        return tuple(float(value) for value in features)

    @property
    def m0_flow_features(self) -> tuple[float, ...]:
        return (*self.m0_common_features, float(self.flow_compression_T))


@dataclass(frozen=True, slots=True)
class PairedSupport:
    """Exact ordered timestamp identity for one period/horizon/family cell."""

    period: str
    horizon_seconds: int
    label_family: str
    m0_common_timestamps: tuple[int, ...]
    m0_flow_timestamps: tuple[int, ...]
    m0_common_support_identifier: str
    m0_flow_support_identifier: str

    def validate(self) -> tuple[int, ...]:
        context = f"{self.period}/{self.label_family}/{self.horizon_seconds}"
        timestamps = assert_ordered_support_identity(
            self.m0_common_timestamps,
            self.m0_flow_timestamps,
            context=context,
        )
        expected = support_identifier(
            label_family=self.label_family,
            horizon_seconds=self.horizon_seconds,
            period=self.period,
            timestamps=timestamps,
        )
        if (
            self.m0_common_support_identifier != expected
            or self.m0_flow_support_identifier != expected
        ):
            raise BlockedSupportError(
                f"BLOCKED_SUPPORT: support identifier mismatch for {context}"
            )
        return timestamps

    @property
    def count(self) -> int:
        return len(self.m0_common_timestamps)

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "period": self.period,
            "horizon_seconds": self.horizon_seconds,
            "label_family": self.label_family,
            "row_count": self.count,
            "m0_common_support_identifier": self.m0_common_support_identifier,
            "m0_flow_support_identifier": self.m0_flow_support_identifier,
            "ordered_support_identical": True,
        }


@dataclass(frozen=True, slots=True)
class FlowPopulationResult:
    """One finite-flow intersection layered over an immutable base population."""

    base_population: PopulationResult
    rows: tuple[FlowRiskRow, ...]
    supports: tuple[PairedSupport, ...]
    kappa: float
    inventory: dict[str, object]

    @property
    def clusters(self):
        return self.base_population.clusters

    def support(
        self,
        period: str,
        horizon_seconds: int,
        label_family: str,
    ) -> PairedSupport:
        matches = [
            support
            for support in self.supports
            if support.period == period
            and support.horizon_seconds == horizon_seconds
            and support.label_family == label_family
        ]
        if len(matches) != 1:
            raise BlockedSupportError(
                "BLOCKED_SUPPORT: paired support record is missing or duplicated"
            )
        matches[0].validate()
        return matches[0]

    def scored_rows(
        self,
        *,
        period: str,
        horizon_seconds: int,
        label_family: str,
    ) -> tuple[FlowRiskRow, ...]:
        support = self.support(period, horizon_seconds, label_family)
        rows = tuple(
            row
            for row in self.rows
            if row.period == period
            and row.base_row.scoreable.get(horizon_seconds, False)
        )
        timestamps = tuple(row.timestamp for row in rows)
        assert_ordered_support_identity(
            timestamps,
            support.m0_common_timestamps,
            context=f"materialized {period}/{label_family}/{horizon_seconds}",
        )
        if not rows:
            raise BlockedSupportError(
                f"BLOCKED_SUPPORT: empty paired support for "
                f"{period}/{label_family}/{horizon_seconds}"
            )
        for row in rows:
            _ = row.m0_common_features
            if len(row.m0_flow_features) != len(M0_FLOW_COLUMNS):
                raise BlockedSupportError("BLOCKED_SUPPORT: M0_FLOW width is not frozen")
        return rows

    def validate(self) -> None:
        if self.kappa != self.base_population.kappa:
            raise BlockedSupportError("BLOCKED_SUPPORT: base D-032 kappa changed")
        if tuple(M0_FLOW_COLUMNS) != (*M0_COLUMNS, "flow_compression_T"):
            raise BlockedSupportError("BLOCKED_SUPPORT: challenger is not flow-only and last")
        if any(
            right.timestamp <= left.timestamp
            for left, right in zip(self.rows, self.rows[1:], strict=False)
        ):
            raise BlockedSupportError("BLOCKED_SUPPORT: paired rows are not strictly ordered")
        periods = tuple(dict.fromkeys(row.period for row in self.base_population.rows))
        expected_supports = {
            (period, horizon, family)
            for period in periods
            for horizon in HORIZONS
            for family in LABEL_FAMILIES
        }
        actual_supports = {
            (support.period, support.horizon_seconds, support.label_family)
            for support in self.supports
        }
        if actual_supports != expected_supports or len(self.supports) != len(expected_supports):
            raise BlockedSupportError(
                "BLOCKED_SUPPORT: period/horizon/family support family is incomplete"
            )
        for support in self.supports:
            support_timestamps = support.validate()
            materialized = tuple(
                row.timestamp
                for row in self.rows
                if row.period == support.period
                and row.base_row.scoreable.get(support.horizon_seconds, False)
            )
            assert_ordered_support_identity(
                materialized,
                support_timestamps,
                context=(
                    f"validate/{support.period}/{support.label_family}/"
                    f"{support.horizon_seconds}"
                ),
            )


def _normalized_flow_values(
    flow_by_timestamp: Mapping[int, float],
) -> tuple[dict[int, float], int]:
    finite: dict[int, float] = {}
    nonfinite_count = 0
    for raw_timestamp, raw_value in flow_by_timestamp.items():
        if isinstance(raw_timestamp, bool) or not isinstance(raw_timestamp, (int, np.integer)):
            raise ValueError("flow mapping keys must be integer UTC epoch seconds")
        timestamp = int(raw_timestamp)
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            nonfinite_count += 1
            continue
        if not math.isfinite(value):
            nonfinite_count += 1
            continue
        finite[timestamp] = value
    return finite, nonfinite_count


def build_flow_population(
    population: PopulationResult,
    flow_by_timestamp: Mapping[int, float],
) -> FlowPopulationResult:
    """Apply one finite-flow mask to both EXP-005 rungs on every score cell."""

    if not isinstance(population, PopulationResult):
        raise TypeError("population must be an existing PopulationResult")
    if not math.isfinite(population.kappa) or population.kappa <= 0.0:
        raise BlockedSupportError("BLOCKED_SUPPORT: base D-032 kappa is invalid")
    base_rows = population.rows
    if any(
        right.timestamp <= left.timestamp
        for left, right in zip(base_rows, base_rows[1:], strict=False)
    ):
        raise BlockedSupportError("BLOCKED_SUPPORT: base population rows are not ordered")

    finite_flow, nonfinite_input_count = _normalized_flow_values(flow_by_timestamp)
    base_timestamps = {row.timestamp for row in base_rows}
    paired_rows = tuple(
        FlowRiskRow(row, finite_flow[row.timestamp])
        for row in base_rows
        if row.timestamp in finite_flow
    )
    periods = tuple(dict.fromkeys(row.period for row in base_rows))
    supports: list[PairedSupport] = []
    support_inventory: dict[str, object] = {}
    for period in periods:
        period_inventory: dict[str, object] = {}
        for horizon in HORIZONS:
            # These are deliberately materialized as two rung lists and asserted,
            # rather than assuming a shared list implies the invariant.
            common = tuple(
                row.timestamp
                for row in paired_rows
                if row.period == period
                and row.base_row.scoreable.get(horizon, False)
            )
            flow = tuple(
                row.timestamp
                for row in paired_rows
                if row.period == period
                and row.base_row.scoreable.get(horizon, False)
                and math.isfinite(row.flow_compression_T)
            )
            assert_ordered_support_identity(
                common,
                flow,
                context=f"{period}/{horizon}",
            )
            horizon_inventory: dict[str, object] = {}
            for label_family in LABEL_FAMILIES:
                identifier = support_identifier(
                    label_family=label_family,
                    horizon_seconds=horizon,
                    period=period,
                    timestamps=common,
                )
                support = PairedSupport(
                    period=period,
                    horizon_seconds=horizon,
                    label_family=label_family,
                    m0_common_timestamps=common,
                    m0_flow_timestamps=flow,
                    m0_common_support_identifier=identifier,
                    m0_flow_support_identifier=identifier,
                )
                support.validate()
                supports.append(support)
                horizon_inventory[label_family] = support.to_dict()
            period_inventory[str(horizon)] = horizon_inventory
        support_inventory[period] = period_inventory

    period_accounting: dict[str, object] = {}
    for period in periods:
        original = [row for row in base_rows if row.period == period]
        finite = [row for row in paired_rows if row.period == period]
        period_accounting[period] = {
            "base_candidate_rows": len(original),
            "finite_flow_rows": len(finite),
            "missing_or_nonfinite_flow_rows": len(original) - len(finite),
            "supports": support_inventory[period],
        }
    result = FlowPopulationResult(
        base_population=population,
        rows=paired_rows,
        supports=tuple(supports),
        kappa=population.kappa,
        inventory={
            "stage": population.inventory.get("stage"),
            "finite_flow_mask_shared_by_rungs": True,
            "m0_common_columns_ordered": list(M0_COLUMNS),
            "m0_flow_columns_ordered": list(M0_FLOW_COLUMNS),
            "input_flow_mapping_rows": len(flow_by_timestamp),
            "finite_flow_mapping_rows": len(finite_flow),
            "nonfinite_or_invalid_flow_mapping_rows": nonfinite_input_count,
            "finite_flow_rows_matching_population": len(paired_rows),
            "finite_flow_rows_outside_population": len(set(finite_flow) - base_timestamps),
            "base_population_inventory": copy.deepcopy(population.inventory),
            "periods": period_accounting,
        },
    )
    result.validate()
    return result


# Explicit aliases make the runner-facing API unambiguous without a generic runner.
build_exp005_flow_population = build_flow_population
build_paired_flow_population = build_flow_population
