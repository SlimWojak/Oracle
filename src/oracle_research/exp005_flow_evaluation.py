"""Frozen paired fitting, evaluation, bootstrap, and disposition for EXP-005."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from oracle_research.exp004_m0_evaluation import alert_episodes
from oracle_research.exp004_m0_model import (
    BOOTSTRAP_DRAWS,
    BOOTSTRAP_SEED,
    CAUSES,
    FINAL_GRADIENT_TOLERANCE,
    OPTIMIZER_FTOL,
    OPTIMIZER_GTOL,
    OPTIMIZER_MAXITER,
    RIDGE_PENALTY,
    BlockedModelError,
    DevelopmentStandardizer,
    FrozenMultinomialState,
    calibration_diagnostic,
    development_alert_threshold,
    directional_probability_metrics,
    draw_week_bootstrap_multiplicities,
    fit_frozen_multinomial,
    relative_brier_skill,
    strict_alerts,
    summarize_bootstrap,
    utc_week_ids,
    utc_week_start,
)
from oracle_research.exp004_m0_population import (
    HORIZONS,
    LABEL_FAMILIES,
    M0_COLUMNS,
    OOS_PERIOD_KEYS,
    Cause,
    ClusterRecord,
    M0RiskRow,
)
from oracle_research.exp005_flow import M0_FLOW_COLUMNS
from oracle_research.exp005_flow_population import (
    BlockedSupportError,
    FlowPopulationResult,
    FlowRiskRow,
    PairedSupport,
    assert_ordered_support_identity,
)

DIRECTIONS = (Cause.UP, Cause.DOWN)
PASS_SKILL = 0.01
FAIL_SKILL = -0.01
PRECISION_MULTIPLE = 2.0
PASS_RECALL = 0.10
MIN_CLUSTERS = 30
LEAD_GATES = {3_600: 900.0, 14_400: 3_600.0}
NEWS_STATUS = "NEWS_NOT_AVAILABLE"


class BlockedFlowEvaluationError(RuntimeError):
    """Raised for a frozen support, state, model, probability, or metric block."""


@dataclass(frozen=True, slots=True)
class FrozenSupportIdentifier:
    """Serializable cryptographic identity for one paired score support."""

    period: str
    horizon_seconds: int
    label_family: str
    row_count: int
    identifier: str

    @classmethod
    def from_support(cls, support: PairedSupport) -> FrozenSupportIdentifier:
        support.validate()
        return cls(
            period=support.period,
            horizon_seconds=support.horizon_seconds,
            label_family=support.label_family,
            row_count=support.count,
            identifier=support.m0_common_support_identifier,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "period": self.period,
            "horizon_seconds": self.horizon_seconds,
            "label_family": self.label_family,
            "row_count": self.row_count,
            "m0_common_support_identifier": self.identifier,
            "m0_flow_support_identifier": self.identifier,
            "ordered_support_identical": True,
        }


@dataclass(frozen=True, slots=True)
class PairedModelBundle:
    """Fresh common and flow fits for one development horizon/family support."""

    label_family: str
    horizon_seconds: int
    support_identifier: str
    development_support_count: int
    m0_common_model: FrozenMultinomialState
    m0_flow_model: FrozenMultinomialState
    m0_common_alert_thresholds: tuple[float, float]
    m0_flow_alert_thresholds: tuple[float, float]
    rv_tertile_cutpoints: tuple[float, float]
    development_climatology: tuple[float, float, float]

    def model(self, rung: str) -> FrozenMultinomialState:
        if rung == "M0_COMMON":
            return self.m0_common_model
        if rung == "M0_FLOW":
            return self.m0_flow_model
        raise BlockedFlowEvaluationError(f"unknown EXP-005 rung: {rung}")

    def thresholds(self, rung: str) -> tuple[float, float]:
        if rung == "M0_COMMON":
            return self.m0_common_alert_thresholds
        if rung == "M0_FLOW":
            return self.m0_flow_alert_thresholds
        raise BlockedFlowEvaluationError(f"unknown EXP-005 rung: {rung}")

    def validate(self) -> None:
        if self.label_family not in LABEL_FAMILIES or self.horizon_seconds not in HORIZONS:
            raise BlockedFlowEvaluationError("frozen bundle identity is invalid")
        if self.development_support_count <= 0 or not self.support_identifier:
            raise BlockedFlowEvaluationError("frozen development support is invalid")
        if self.m0_common_model.support_identifier != self.support_identifier:
            raise BlockedFlowEvaluationError("M0_COMMON model support identifier changed")
        if self.m0_flow_model.support_identifier != self.support_identifier:
            raise BlockedFlowEvaluationError("M0_FLOW model support identifier changed")
        if self.m0_common_model.column_names != tuple(M0_COLUMNS):
            raise BlockedFlowEvaluationError("M0_COMMON column order changed")
        if self.m0_flow_model.column_names != tuple(M0_FLOW_COLUMNS):
            raise BlockedFlowEvaluationError("M0_FLOW column order changed")
        for thresholds in (
            self.m0_common_alert_thresholds,
            self.m0_flow_alert_thresholds,
        ):
            if len(thresholds) != 2 or not all(
                math.isfinite(value) and 0.0 <= value <= 1.0 for value in thresholds
            ):
                raise BlockedFlowEvaluationError("frozen alert thresholds are invalid")
        if len(self.rv_tertile_cutpoints) != 2 or not all(
            math.isfinite(value) for value in self.rv_tertile_cutpoints
        ):
            raise BlockedFlowEvaluationError("frozen RV tertiles are invalid")
        if self.rv_tertile_cutpoints[0] > self.rv_tertile_cutpoints[1]:
            raise BlockedFlowEvaluationError("frozen RV tertiles are reversed")
        if len(self.development_climatology) != 3 or not all(
            math.isfinite(value) and 0.0 <= value <= 1.0
            for value in self.development_climatology
        ):
            raise BlockedFlowEvaluationError("development climatology is invalid")
        if not math.isclose(
            sum(self.development_climatology), 1.0, rel_tol=0.0, abs_tol=1e-12
        ):
            raise BlockedFlowEvaluationError("development climatology does not sum to one")

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "label_family": self.label_family,
            "horizon_seconds": self.horizon_seconds,
            "paired_development_support_identifier": self.support_identifier,
            "development_support_count": self.development_support_count,
            "M0_COMMON": {
                "columns_ordered": list(M0_COLUMNS),
                "model": self.m0_common_model.to_dict(),
                "alert_thresholds_up_down_strict": list(
                    self.m0_common_alert_thresholds
                ),
            },
            "M0_FLOW": {
                "columns_ordered": list(M0_FLOW_COLUMNS),
                "model": self.m0_flow_model.to_dict(),
                "alert_thresholds_up_down_strict": list(self.m0_flow_alert_thresholds),
            },
            "rv_tertile_cutpoints_linear": list(self.rv_tertile_cutpoints),
            "development_climatology_up_down_none": list(self.development_climatology),
        }


@dataclass(frozen=True, slots=True)
class FrozenFlowState:
    """Complete immutable EXP-005 fit and support state."""

    kappa: float
    bundles: tuple[PairedModelBundle, ...]
    support_identifiers: tuple[FrozenSupportIdentifier, ...]

    def bundle(self, label_family: str, horizon_seconds: int) -> PairedModelBundle:
        matches = [
            bundle
            for bundle in self.bundles
            if bundle.label_family == label_family
            and bundle.horizon_seconds == horizon_seconds
        ]
        if len(matches) != 1:
            raise BlockedFlowEvaluationError("frozen paired model bundle is missing or duplicated")
        matches[0].validate()
        return matches[0]

    def support(
        self, period: str, horizon_seconds: int, label_family: str
    ) -> FrozenSupportIdentifier:
        matches = [
            support
            for support in self.support_identifiers
            if support.period == period
            and support.horizon_seconds == horizon_seconds
            and support.label_family == label_family
        ]
        if len(matches) != 1:
            raise BlockedFlowEvaluationError("frozen support identifier is missing or duplicated")
        return matches[0]

    def validate(self) -> None:
        if not math.isfinite(self.kappa) or self.kappa <= 0.0:
            raise BlockedFlowEvaluationError("frozen D-032 kappa is invalid")
        expected = {(family, horizon) for family in LABEL_FAMILIES for horizon in HORIZONS}
        actual = {(bundle.label_family, bundle.horizon_seconds) for bundle in self.bundles}
        if actual != expected or len(self.bundles) != len(expected):
            raise BlockedFlowEvaluationError("frozen bundle family is incomplete or duplicated")
        for bundle in self.bundles:
            bundle.validate()
        support_keys = [
            (support.period, support.horizon_seconds, support.label_family)
            for support in self.support_identifiers
        ]
        if len(support_keys) != len(set(support_keys)):
            raise BlockedFlowEvaluationError("frozen support identifiers are duplicated")
        expected_supports = {
            ("development", horizon, family)
            for horizon in HORIZONS
            for family in LABEL_FAMILIES
        }
        if set(support_keys) != expected_supports:
            raise BlockedFlowEvaluationError(
                "model state must freeze development score-support identifiers only"
            )
        if any(
            support.row_count < 0 or not support.identifier
            for support in self.support_identifiers
        ):
            raise BlockedFlowEvaluationError("frozen support identifier is invalid")

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "experiment": "EXP-005",
            "comparison": ["M0_COMMON", "M0_FLOW"],
            "kappa_six_decimals_preserved_from_d032": self.kappa,
            "column_orders": {
                "M0_COMMON": list(M0_COLUMNS),
                "M0_FLOW": list(M0_FLOW_COLUMNS),
            },
            "support_identifiers": [
                support.to_dict() for support in self.support_identifiers
            ],
            "bundles": [bundle.to_dict() for bundle in self.bundles],
        }

    def to_json(self) -> str:
        """Serialize canonically; NaN/Infinity are forbidden."""

        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> FrozenFlowState:
        """Load and verify every frozen field with exact canonical round-trip."""

        try:
            if payload["experiment"] != "EXP-005":
                raise ValueError("frozen state experiment identity changed")
            if payload["comparison"] != ["M0_COMMON", "M0_FLOW"]:
                raise ValueError("frozen state comparison identity changed")
            if payload["column_orders"] != {
                "M0_COMMON": list(M0_COLUMNS),
                "M0_FLOW": list(M0_FLOW_COLUMNS),
            }:
                raise ValueError("frozen state column order changed")
            supports_raw = payload["support_identifiers"]
            bundles_raw = payload["bundles"]
            if not isinstance(supports_raw, list) or not isinstance(bundles_raw, list):
                raise ValueError("frozen state collections are invalid")
            supports = tuple(_support_from_dict(item) for item in supports_raw)
            bundles = tuple(_bundle_from_dict(item) for item in bundles_raw)
            state = cls(
                kappa=float(payload["kappa_six_decimals_preserved_from_d032"]),
                bundles=bundles,
                support_identifiers=supports,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise BlockedFlowEvaluationError(f"invalid frozen EXP-005 state: {error}") from error
        state.validate()
        if state.to_dict() != dict(payload):
            raise BlockedFlowEvaluationError("frozen EXP-005 state failed exact round-trip")
        return state

    @classmethod
    def from_json(cls, text: str) -> FrozenFlowState:
        try:
            payload = json.loads(text)
        except (TypeError, json.JSONDecodeError) as error:
            raise BlockedFlowEvaluationError("invalid frozen EXP-005 JSON") from error
        if not isinstance(payload, dict):
            raise BlockedFlowEvaluationError("frozen EXP-005 JSON must be an object")
        return cls.from_dict(payload)


def _model_from_dict(
    payload: object,
    *,
    expected_columns: tuple[str, ...],
) -> FrozenMultinomialState:
    if not isinstance(payload, dict):
        raise ValueError("frozen model is not an object")
    standardizer_raw = payload.get("standardizer")
    optimizer = payload.get("optimizer")
    if not isinstance(standardizer_raw, dict) or not isinstance(optimizer, dict):
        raise ValueError("frozen model scaler/optimizer is invalid")
    if payload.get("causes_in_probability_order") != list(CAUSES):
        raise ValueError("frozen cause order changed")
    if payload.get("none_is_reference") is not True:
        raise ValueError("NONE is no longer the frozen reference")
    if optimizer != {
        "method": "L-BFGS-B",
        "initialization": "all_zero",
        "maxiter": OPTIMIZER_MAXITER,
        "ftol": OPTIMIZER_FTOL,
        "gtol": OPTIMIZER_GTOL,
        "iterations": optimizer.get("iterations"),
    }:
        raise ValueError("frozen optimizer contract changed")
    if standardizer_raw.get("column_names") != list(expected_columns):
        raise ValueError("frozen scaler column order changed")
    means = tuple(float(value) for value in standardizer_raw["means"])
    scales = tuple(float(value) for value in standardizer_raw["population_scales_ddof0"])
    intercepts = tuple(float(value) for value in payload["intercepts_up_down"])
    slopes = tuple(tuple(float(value) for value in row) for row in payload["slopes_up_down"])
    if (
        len(means) != len(expected_columns)
        or len(scales) != len(expected_columns)
        or len(intercepts) != 2
        or len(slopes) != 2
        or any(len(row) != len(expected_columns) for row in slopes)
    ):
        raise ValueError("frozen coefficient/scaler dimensions changed")
    numeric = (*means, *scales, *intercepts, *(value for row in slopes for value in row))
    if not all(math.isfinite(value) for value in numeric) or any(value <= 0 for value in scales):
        raise ValueError("frozen coefficient/scaler values are invalid")
    state = FrozenMultinomialState(
        support_identifier=str(payload["support_identifier"]),
        standardizer=DevelopmentStandardizer(expected_columns, means, scales),
        intercepts_up_down=(intercepts[0], intercepts[1]),
        slopes_up_down=(slopes[0], slopes[1]),
        ridge_penalty=float(payload["ridge_penalty_slopes_only"]),
        objective=float(payload["objective"]),
        final_gradient_infinity_norm=float(payload["final_gradient_infinity_norm"]),
        iterations=int(optimizer["iterations"]),
    )
    if (
        state.ridge_penalty != RIDGE_PENALTY
        or not math.isfinite(state.objective)
        or not math.isfinite(state.final_gradient_infinity_norm)
        or state.final_gradient_infinity_norm > FINAL_GRADIENT_TOLERANCE
        or state.iterations < 0
    ):
        raise ValueError("frozen model integrity values changed")
    if state.to_dict() != payload:
        raise ValueError("frozen model failed exact round-trip")
    return state


def _support_from_dict(payload: object) -> FrozenSupportIdentifier:
    if not isinstance(payload, dict):
        raise ValueError("frozen support is not an object")
    common = str(payload["m0_common_support_identifier"])
    flow = str(payload["m0_flow_support_identifier"])
    if common != flow or payload.get("ordered_support_identical") is not True:
        raise ValueError("frozen paired support identity changed")
    support = FrozenSupportIdentifier(
        period=str(payload["period"]),
        horizon_seconds=int(payload["horizon_seconds"]),
        label_family=str(payload["label_family"]),
        row_count=int(payload["row_count"]),
        identifier=common,
    )
    if support.to_dict() != payload:
        raise ValueError("frozen support failed exact round-trip")
    return support


def _bundle_from_dict(payload: object) -> PairedModelBundle:
    if not isinstance(payload, dict):
        raise ValueError("frozen bundle is not an object")
    common_raw = payload["M0_COMMON"]
    flow_raw = payload["M0_FLOW"]
    if not isinstance(common_raw, dict) or not isinstance(flow_raw, dict):
        raise ValueError("frozen rung is not an object")
    if common_raw.get("columns_ordered") != list(M0_COLUMNS):
        raise ValueError("M0_COMMON columns changed")
    if flow_raw.get("columns_ordered") != list(M0_FLOW_COLUMNS):
        raise ValueError("M0_FLOW columns changed")
    bundle = PairedModelBundle(
        label_family=str(payload["label_family"]),
        horizon_seconds=int(payload["horizon_seconds"]),
        support_identifier=str(payload["paired_development_support_identifier"]),
        development_support_count=int(payload["development_support_count"]),
        m0_common_model=_model_from_dict(
            common_raw["model"], expected_columns=tuple(M0_COLUMNS)
        ),
        m0_flow_model=_model_from_dict(
            flow_raw["model"], expected_columns=tuple(M0_FLOW_COLUMNS)
        ),
        m0_common_alert_thresholds=tuple(
            float(value) for value in common_raw["alert_thresholds_up_down_strict"]
        ),
        m0_flow_alert_thresholds=tuple(
            float(value) for value in flow_raw["alert_thresholds_up_down_strict"]
        ),
        rv_tertile_cutpoints=tuple(
            float(value) for value in payload["rv_tertile_cutpoints_linear"]
        ),
        development_climatology=tuple(
            float(value) for value in payload["development_climatology_up_down_none"]
        ),
    )
    bundle.validate()
    if bundle.to_dict() != payload:
        raise ValueError("frozen bundle failed exact round-trip")
    return bundle


def _feature_matrix(rows: Sequence[FlowRiskRow], rung: str) -> np.ndarray:
    if rung == "M0_COMMON":
        return np.asarray([row.m0_common_features for row in rows], dtype=np.float64)
    if rung == "M0_FLOW":
        return np.asarray([row.m0_flow_features for row in rows], dtype=np.float64)
    raise BlockedFlowEvaluationError(f"unknown EXP-005 rung: {rung}")


def _causes(
    rows: Sequence[FlowRiskRow], label_family: str, horizon_seconds: int
) -> np.ndarray:
    values = [
        row.base_row.outcomes[(label_family, horizon_seconds)].cause.value for row in rows
    ]
    if any(value not in CAUSES for value in values):
        raise BlockedFlowEvaluationError("paired support contains an unscored cause")
    return np.asarray(values)


def fit_flow_models(population: FlowPopulationResult) -> FrozenFlowState:
    """Fit fresh deterministic ``M0_COMMON`` and ``M0_FLOW`` development models."""

    try:
        population.validate()
        if population.inventory.get("stage") not in {"development", "full"}:
            raise BlockedFlowEvaluationError("population stage is invalid")
        bundles: list[PairedModelBundle] = []
        for horizon in HORIZONS:
            for label_family in LABEL_FAMILIES:
                rows = population.scored_rows(
                    period="development",
                    horizon_seconds=horizon,
                    label_family=label_family,
                )
                support = population.support("development", horizon, label_family)
                assert_ordered_support_identity(
                    tuple(row.timestamp for row in rows),
                    support.m0_flow_timestamps,
                    context=f"fit/development/{label_family}/{horizon}",
                )
                common_predictors = _feature_matrix(rows, "M0_COMMON")
                flow_predictors = _feature_matrix(rows, "M0_FLOW")
                causes = _causes(rows, label_family, horizon)
                try:
                    # Both calls are intentional fresh fits.  No banked M0 state is reused.
                    common_model = fit_frozen_multinomial(
                        common_predictors,
                        causes,
                        column_names=M0_COLUMNS,
                        support_identifier=support.m0_common_support_identifier,
                    )
                    flow_model = fit_frozen_multinomial(
                        flow_predictors,
                        causes,
                        column_names=M0_FLOW_COLUMNS,
                        support_identifier=support.m0_flow_support_identifier,
                    )
                except BlockedModelError as error:
                    raise BlockedFlowEvaluationError(str(error)) from error
                common_probabilities = common_model.predict_proba(
                    common_predictors, column_names=M0_COLUMNS
                )
                flow_probabilities = flow_model.predict_proba(
                    flow_predictors, column_names=M0_FLOW_COLUMNS
                )
                rv_cutpoints = np.quantile(
                    common_predictors[:, 2],
                    [1.0 / 3.0, 2.0 / 3.0],
                    method="linear",
                )
                climatology = tuple(float(np.mean(causes == cause)) for cause in CAUSES)
                bundles.append(
                    PairedModelBundle(
                        label_family=label_family,
                        horizon_seconds=horizon,
                        support_identifier=support.m0_common_support_identifier,
                        development_support_count=len(rows),
                        m0_common_model=common_model,
                        m0_flow_model=flow_model,
                        m0_common_alert_thresholds=(
                            development_alert_threshold(common_probabilities[:, 0]),
                            development_alert_threshold(common_probabilities[:, 1]),
                        ),
                        m0_flow_alert_thresholds=(
                            development_alert_threshold(flow_probabilities[:, 0]),
                            development_alert_threshold(flow_probabilities[:, 1]),
                        ),
                        rv_tertile_cutpoints=(
                            float(rv_cutpoints[0]),
                            float(rv_cutpoints[1]),
                        ),
                        development_climatology=climatology,
                    )
                )
        state = FrozenFlowState(
            kappa=population.kappa,
            bundles=tuple(bundles),
            support_identifiers=tuple(
                FrozenSupportIdentifier.from_support(support)
                for support in population.supports
                if support.period == "development"
            ),
        )
        state.validate()
        FrozenFlowState.from_json(state.to_json())
        return state
    except BlockedSupportError as error:
        raise BlockedFlowEvaluationError(str(error)) from error


def _cluster_diagnostics(
    *,
    rows: Sequence[FlowRiskRow],
    label_family: str,
    horizon_seconds: int,
    direction: Cause,
    alerts: np.ndarray,
    cluster_lookup: Mapping[str, ClusterRecord],
) -> tuple[list[str], dict[str, bool], dict[str, float], dict[str, str]]:
    eligible: dict[str, list[M0RiskRow]] = {}
    alerted: dict[str, list[M0RiskRow]] = {}
    for paired_row, alert in zip(rows, alerts.tolist(), strict=True):
        row = paired_row.base_row
        outcome = row.outcomes[(label_family, horizon_seconds)]
        if outcome.cause is not direction:
            continue
        cluster_id = row.cluster_ids.get((label_family, horizon_seconds))
        if cluster_id is None or cluster_id not in cluster_lookup:
            raise BlockedFlowEvaluationError("positive score row has no frozen cluster")
        eligible.setdefault(cluster_id, []).append(row)
        if alert:
            alerted.setdefault(cluster_id, []).append(row)
    eligible_ids = sorted(eligible, key=lambda key: cluster_lookup[key].start_timestamp)
    recalled = {cluster_id: cluster_id in alerted for cluster_id in eligible_ids}
    leads: dict[str, float] = {}
    morphology: dict[str, str] = {}
    for cluster_id in eligible_ids:
        cluster = cluster_lookup[cluster_id]
        morphology[cluster_id] = cluster.morphology
        if not recalled[cluster_id]:
            continue
        earliest_alert = min(row.timestamp for row in alerted[cluster_id])
        passage_inventory = (
            cluster.up_passage_timestamps
            if direction is Cause.UP
            else cluster.down_passage_timestamps
        )
        subsequent = [value for value in passage_inventory if value >= earliest_alert]
        if not subsequent:
            raise BlockedFlowEvaluationError(
                "recalled cluster has no subsequent target-direction passage"
            )
        leads[cluster_id] = float(min(subsequent) - earliest_alert)
    return eligible_ids, recalled, leads, morphology


def _rung_point(
    *,
    rows: Sequence[FlowRiskRow],
    probabilities: np.ndarray,
    bundle: PairedModelBundle,
    rung: str,
    direction: Cause,
    cluster_lookup: Mapping[str, ClusterRecord],
) -> tuple[dict[str, object], dict[str, object]]:
    direction_index = 0 if direction is Cause.UP else 1
    causes = _causes(rows, bundle.label_family, bundle.horizon_seconds)
    targets = (causes == direction.value).astype(np.int8)
    directional = probabilities[:, direction_index]
    metrics = directional_probability_metrics(targets, directional)
    threshold = bundle.thresholds(rung)[direction_index]
    alerts = strict_alerts(directional, threshold)
    timestamps = np.asarray([row.timestamp for row in rows], dtype=np.int64)
    episodes = alert_episodes(timestamps, alerts, targets)
    eligible_ids, recalled, leads, morphology = _cluster_diagnostics(
        rows=rows,
        label_family=bundle.label_family,
        horizon_seconds=bundle.horizon_seconds,
        direction=direction,
        alerts=alerts,
        cluster_lookup=cluster_lookup,
    )
    lead_values = [leads[key] for key in eligible_ids if recalled[key]]
    point = {
        **metrics.to_dict(),
        "alert_threshold_strict_gt": threshold,
        "alert_rows": int(np.count_nonzero(alerts)),
        "alert_share": float(np.mean(alerts)),
        "alert_episode_count": len(episodes),
        "episode_precision": (
            float(np.mean([episode.contains_target for episode in episodes]))
            if episodes
            else None
        ),
        "eligible_cluster_count": len(eligible_ids),
        "recalled_cluster_count": sum(recalled.values()),
        "cluster_recall": (
            float(np.mean([recalled[key] for key in eligible_ids]))
            if eligible_ids
            else None
        ),
        "median_lead_seconds": float(np.median(lead_values)) if lead_values else None,
    }
    context: dict[str, object] = {
        "targets": targets,
        "probabilities": directional,
        "timestamps": timestamps,
        "alerts": alerts,
        "episodes": episodes,
        "eligible_cluster_ids": eligible_ids,
        "recalled": recalled,
        "leads": leads,
        "morphology": morphology,
        "cluster_lookup": cluster_lookup,
        "label_family": bundle.label_family,
        "horizon_seconds": bundle.horizon_seconds,
        "direction": direction,
    }
    return point, context


def _session(timestamp: int) -> str:
    hour = datetime.fromtimestamp(timestamp, tz=UTC).hour
    if hour < 8:
        return "ASIA"
    if hour < 16:
        return "EUROPE"
    return "AMERICAS"


def _volatility_slice(sigma: float, cutpoints: tuple[float, float]) -> str:
    if sigma <= cutpoints[0]:
        return "LOW"
    if sigma <= cutpoints[1]:
        return "MID"
    return "HIGH"


def _row_slice(
    *,
    rows: Sequence[FlowRiskRow],
    context: Mapping[str, object],
    mask: np.ndarray,
) -> dict[str, object]:
    selected_rows = tuple(row for row, keep in zip(rows, mask.tolist(), strict=True) if keep)
    targets = np.asarray(context["targets"])[mask]
    probabilities = np.asarray(context["probabilities"])[mask]
    alerts = np.asarray(context["alerts"])[mask]
    timestamps = np.asarray(context["timestamps"])[mask]
    if not selected_rows:
        return {
            "row_count": 0,
            "alert_episode_count": 0,
            "eligible_cluster_count": 0,
            "interpretation": "EMPTY_REPORT_ONLY",
        }
    metrics = directional_probability_metrics(targets, probabilities)
    episodes = alert_episodes(timestamps, alerts, targets)
    eligible_ids, recalled, leads, _morphology = _cluster_diagnostics(
        rows=selected_rows,
        label_family=str(context["label_family"]),
        horizon_seconds=int(context["horizon_seconds"]),
        direction=context["direction"],
        alerts=alerts,
        cluster_lookup=context["cluster_lookup"],
    )
    recalled_ids = [key for key in eligible_ids if recalled[key]]
    return {
        **metrics.to_dict(),
        "row_count": len(selected_rows),
        "alert_rows": int(np.count_nonzero(alerts)),
        "alert_share": float(np.mean(alerts)),
        "alert_episode_count": len(episodes),
        "episode_precision": (
            float(np.mean([episode.contains_target for episode in episodes]))
            if episodes
            else None
        ),
        "eligible_cluster_count": len(eligible_ids),
        "recalled_cluster_count": len(recalled_ids),
        "cluster_recall": (
            float(len(recalled_ids) / len(eligible_ids)) if eligible_ids else None
        ),
        "median_lead_seconds": (
            float(np.median([leads[key] for key in recalled_ids]))
            if recalled_ids
            else None
        ),
        "interpretation": "REPORT_ONLY_LT30" if len(eligible_ids) < 30 else "DESCRIPTIVE",
    }


def _slices(
    *,
    rows: Sequence[FlowRiskRow],
    context: Mapping[str, object],
    rv_cutpoints: tuple[float, float],
) -> dict[str, object]:
    sigmas = np.asarray([row.base_row.sigma for row in rows], dtype=np.float64)
    vol_names = np.asarray(
        [_volatility_slice(float(sigma), rv_cutpoints) for sigma in sigmas]
    )
    session_names = np.asarray([_session(row.timestamp) for row in rows])
    volatility = {
        name: _row_slice(rows=rows, context=context, mask=vol_names == name)
        for name in ("LOW", "MID", "HIGH")
    }
    sessions = {
        name: _row_slice(rows=rows, context=context, mask=session_names == name)
        for name in ("ASIA", "EUROPE", "AMERICAS")
    }
    eligible_ids = list(context["eligible_cluster_ids"])
    recalled = dict(context["recalled"])
    leads = dict(context["leads"])
    morphology = dict(context["morphology"])
    morphology_slices: dict[str, object] = {}
    for name in ("ONE_WAY", "MIXED"):
        ids = [key for key in eligible_ids if morphology[key] == name]
        recalled_ids = [key for key in ids if recalled[key]]
        morphology_slices[name] = {
            "eligible_cluster_count": len(ids),
            "recalled_cluster_count": len(recalled_ids),
            "cluster_recall": (
                float(len(recalled_ids) / len(ids)) if ids else None
            ),
            "median_lead_seconds": (
                float(np.median([leads[key] for key in recalled_ids]))
                if recalled_ids
                else None
            ),
            "probability_metrics": "PROHIBITED_FUTURE_OUTCOME_SLICE",
            "interpretation": "REPORT_ONLY_LT30" if len(ids) < 30 else "DESCRIPTIVE",
        }
    morphology_slices["NO_EVENT"] = {
        "row_count": int(np.count_nonzero(np.asarray(context["targets"]) == 0)),
        "probability_metrics": "PROHIBITED_FUTURE_OUTCOME_SLICE",
    }
    return {
        "volatility": volatility,
        "utc_session": sessions,
        "cluster_morphology_recall_lead_only": morphology_slices,
        "news": NEWS_STATUS,
    }


def _weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    total = int(np.sum(weights))
    if total <= 0:
        raise BlockedFlowEvaluationError("bootstrap draw has zero applicable weight")
    return float(np.sum(values * weights) / total)


def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    positive = weights > 0
    if not bool(np.any(positive)):
        raise BlockedFlowEvaluationError("bootstrap draw has no recalled cluster lead")
    return float(np.median(np.repeat(values[positive], weights[positive])))


def _summary(
    values: np.ndarray, *, requested_draws: int, undefined_key: str
) -> dict[str, object] | None:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None
    return {
        **summarize_bootstrap(finite).to_dict(),
        "requested_draws": requested_draws,
        undefined_key: requested_draws - int(finite.size),
    }


def _bootstrap_rung(
    context: Mapping[str, object],
    family_draws,
) -> tuple[dict[str, object], np.ndarray]:
    targets = np.asarray(context["targets"], dtype=np.float64)
    probabilities = np.asarray(context["probabilities"], dtype=np.float64)
    timestamps = np.asarray(context["timestamps"], dtype=np.int64)
    weights = family_draws.index_multiplicities(utc_week_ids(timestamps))
    errors = np.square(probabilities - targets)
    briers = np.full(family_draws.draws, np.nan)
    event_rates = np.full(family_draws.draws, np.nan)
    mean_probabilities = np.full(family_draws.draws, np.nan)
    alert_shares = np.full(family_draws.draws, np.nan)
    calibration_intercepts = np.full(family_draws.draws, np.nan)
    calibration_slopes = np.full(family_draws.draws, np.nan)
    alerts = np.asarray(context["alerts"], dtype=np.float64)
    for draw in range(family_draws.draws):
        if int(np.sum(weights[draw])) <= 0:
            continue
        briers[draw] = _weighted_mean(errors, weights[draw])
        event_rates[draw] = _weighted_mean(targets, weights[draw])
        mean_probabilities[draw] = _weighted_mean(probabilities, weights[draw])
        alert_shares[draw] = _weighted_mean(alerts, weights[draw])
        diagnostic = calibration_diagnostic(
            np.repeat(targets, weights[draw]),
            np.repeat(probabilities, weights[draw]),
        )
        if diagnostic is not None:
            calibration_intercepts[draw] = diagnostic.intercept
            calibration_slopes[draw] = diagnostic.slope

    episodes = list(context["episodes"])
    if episodes:
        episode_values = np.asarray(
            [episode.contains_target for episode in episodes], dtype=np.float64
        )
        episode_weights = family_draws.index_multiplicities(
            [episode.week_start_timestamp for episode in episodes]
        )
        precisions = np.asarray(
            [
                _weighted_mean(episode_values, episode_weights[draw])
                if int(np.sum(episode_weights[draw])) > 0
                else np.nan
                for draw in range(family_draws.draws)
            ]
        )
    else:
        precisions = np.asarray([], dtype=np.float64)

    eligible_ids = list(context["eligible_cluster_ids"])
    recalled = dict(context["recalled"])
    leads = dict(context["leads"])
    cluster_lookup = context["cluster_lookup"]
    recalls = np.asarray([], dtype=np.float64)
    boot_leads = np.asarray([], dtype=np.float64)
    if eligible_ids:
        cluster_values = np.asarray([recalled[key] for key in eligible_ids], dtype=float)
        cluster_weights = family_draws.index_multiplicities(
            [utc_week_start(cluster_lookup[key].start_timestamp) for key in eligible_ids]
        )
        recalls = np.asarray(
            [
                _weighted_mean(cluster_values, cluster_weights[draw])
                if int(np.sum(cluster_weights[draw])) > 0
                else np.nan
                for draw in range(family_draws.draws)
            ]
        )
        recalled_ids = [key for key in eligible_ids if recalled[key]]
        if recalled_ids:
            lead_values = np.asarray([leads[key] for key in recalled_ids])
            lead_weights = family_draws.index_multiplicities(
                [utc_week_start(cluster_lookup[key].start_timestamp) for key in recalled_ids]
            )
            boot_leads = np.asarray(
                [
                    _weighted_median(lead_values, lead_weights[draw])
                    if int(np.sum(lead_weights[draw])) > 0
                    else np.nan
                    for draw in range(family_draws.draws)
                ]
            )
    return (
        {
            "brier_score": _summary(
                briers, requested_draws=family_draws.draws, undefined_key="undefined_draws_no_rows"
            ),
            "event_rate": _summary(
                event_rates,
                requested_draws=family_draws.draws,
                undefined_key="undefined_draws_no_rows",
            ),
            "mean_probability": _summary(
                mean_probabilities,
                requested_draws=family_draws.draws,
                undefined_key="undefined_draws_no_rows",
            ),
            "calibration_intercept": _summary(
                calibration_intercepts,
                requested_draws=family_draws.draws,
                undefined_key="undefined_draws_calibration",
            ),
            "calibration_slope": _summary(
                calibration_slopes,
                requested_draws=family_draws.draws,
                undefined_key="undefined_draws_calibration",
            ),
            "alert_share": _summary(
                alert_shares,
                requested_draws=family_draws.draws,
                undefined_key="undefined_draws_no_rows",
            ),
            "episode_precision": _summary(
                precisions,
                requested_draws=family_draws.draws,
                undefined_key="undefined_draws_no_episode",
            ),
            "cluster_recall": _summary(
                recalls,
                requested_draws=family_draws.draws,
                undefined_key="undefined_draws_no_eligible_cluster",
            ),
            "median_lead_seconds": _summary(
                boot_leads,
                requested_draws=family_draws.draws,
                undefined_key="undefined_draws_no_recalled_cluster",
            ),
        },
        briers,
    )


def paired_brier_skill_draws(
    m0_common_briers: Sequence[float] | np.ndarray,
    m0_flow_briers: Sequence[float] | np.ndarray,
) -> np.ndarray:
    """Compute the paired ratio ``1 - BS_FLOW / BS_COMMON`` draw by draw."""

    common = np.asarray(m0_common_briers, dtype=np.float64)
    flow = np.asarray(m0_flow_briers, dtype=np.float64)
    if common.ndim != 1 or flow.shape != common.shape:
        raise BlockedFlowEvaluationError("paired bootstrap Brier vectors do not align")
    result = np.full(common.shape, np.nan, dtype=np.float64)
    valid = np.isfinite(common) & np.isfinite(flow) & (common > 0.0) & (flow >= 0.0)
    result[valid] = 1.0 - flow[valid] / common[valid]
    return result


def _validate_state_support(
    population: FlowPopulationResult,
    state: FrozenFlowState,
) -> None:
    if state.kappa != population.kappa:
        raise BlockedFlowEvaluationError("base D-032 kappa differs from frozen state")
    # OOS label-score supports do not exist in the pre-receipt model state.  They
    # are computed and reported from the consumed full population below.
    for support in (
        candidate for candidate in population.supports if candidate.period == "development"
    ):
        frozen = state.support(
            support.period, support.horizon_seconds, support.label_family
        )
        support.validate()
        if (
            frozen.row_count != support.count
            or frozen.identifier != support.m0_common_support_identifier
            or frozen.identifier != support.m0_flow_support_identifier
        ):
            raise BlockedFlowEvaluationError(
                "BLOCKED_SUPPORT: full population differs from frozen support"
            )


def mechanical_disposition(
    family_skills: Mapping[tuple[str, str], float],
    challenger_cells: Mapping[tuple[str, str, int, str], Mapping[str, object]],
    *,
    integrity_failures: Sequence[str] = (),
) -> str:
    """Apply the exact EXP-005 PASS/FAIL/NULL/BLOCKED hierarchy."""

    if integrity_failures:
        return "BLOCKED"
    expected_families = {
        (period, family) for period in OOS_PERIOD_KEYS for family in LABEL_FAMILIES
    }
    expected_cells = {
        (period, family, horizon, direction.value)
        for period in OOS_PERIOD_KEYS
        for family in LABEL_FAMILIES
        for horizon in HORIZONS
        for direction in DIRECTIONS
    }
    if set(family_skills) != expected_families or set(challenger_cells) != expected_cells:
        return "BLOCKED"
    if any(not math.isfinite(float(value)) for value in family_skills.values()):
        return "BLOCKED"
    for cell in challenger_cells.values():
        try:
            event_rate = float(cell["event_rate"])
            cluster_count = int(cell["eligible_cluster_count"])
        except (KeyError, TypeError, ValueError):
            return "BLOCKED"
        if not math.isfinite(event_rate) or not 0.0 <= event_rate <= 1.0 or cluster_count < 0:
            return "BLOCKED"
        for metric in ("episode_precision", "cluster_recall"):
            value = cell.get(metric)
            if value is None:
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return "BLOCKED"
            if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
                return "BLOCKED"
        lead = cell.get("median_lead_seconds")
        if lead is not None:
            try:
                numeric_lead = float(lead)
            except (TypeError, ValueError):
                return "BLOCKED"
            if not math.isfinite(numeric_lead) or numeric_lead < 0.0:
                return "BLOCKED"

    fail = all(float(family_skills[key]) <= FAIL_SKILL for key in expected_families)
    passed = all(float(family_skills[key]) >= PASS_SKILL for key in expected_families)
    if passed:
        for key in expected_cells:
            horizon = key[2]
            cell = challenger_cells[key]
            precision = cell.get("episode_precision")
            recall = cell.get("cluster_recall")
            lead = cell.get("median_lead_seconds")
            passed = passed and (
                precision is not None
                and math.isfinite(float(precision))
                and float(precision) >= PRECISION_MULTIPLE * float(cell["event_rate"])
                and recall is not None
                and math.isfinite(float(recall))
                and float(recall) >= PASS_RECALL
                and lead is not None
                and math.isfinite(float(lead))
                and float(lead) >= LEAD_GATES[horizon]
                and int(cell["eligible_cluster_count"]) >= MIN_CLUSTERS
            )
    if passed:
        return "PASS"
    if fail:
        return "FAIL"
    return "NULL"


def evaluate_flow_models(
    population: FlowPopulationResult,
    state: FrozenFlowState,
    *,
    bootstrap_draws: int = BOOTSTRAP_DRAWS,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> dict[str, object]:
    """Evaluate both frozen rungs on full paired support without any refit."""

    try:
        population.validate()
        state.validate()
        if population.inventory.get("stage") != "full":
            raise BlockedFlowEvaluationError("OOS evaluation requires a full-stage population")
        _validate_state_support(population, state)
        cluster_lookup = {
            cluster.cluster_id: cluster for cluster in population.base_population.clusters
        }
        all_rows = {
            period: {
                horizon: {
                    family: population.scored_rows(
                        period=period,
                        horizon_seconds=horizon,
                        label_family=family,
                    )
                    for family in LABEL_FAMILIES
                }
                for horizon in HORIZONS
            }
            for period in OOS_PERIOD_KEYS
        }
        family_weeks = np.unique(
            np.concatenate(
                [
                    utc_week_ids([row.timestamp for row in rows])
                    for period_rows in all_rows.values()
                    for horizon_rows in period_rows.values()
                    for rows in horizon_rows.values()
                ]
            )
        )
        draws = draw_week_bootstrap_multiplicities(
            family_weeks, draws=bootstrap_draws, seed=bootstrap_seed
        )
        report: dict[str, object] = {
            "experiment": "EXP-005",
            "comparison": "M0_FLOW versus freshly fitted M0_COMMON on identical rows",
            "population_accounting": population.inventory,
            "support_accounting": [support.to_dict() for support in population.supports],
            "news": NEWS_STATUS,
            "bootstrap": {
                "block": "UTC_WEEK_FAMILY_WIDE_ONE_DRAW_ALL_LINKED_OBJECTS_AND_RUNGS",
                "draws": bootstrap_draws,
                "seed": bootstrap_seed,
                "se_ddof": 1,
                "paired_skill_formula": "1 - BS_M0_FLOW / BS_M0_COMMON per draw",
                "rungs_drawn_independently": False,
            },
            "frozen_state_sha256": state.sha256,
            "frozen_models_coefficients_scalers_thresholds": state.to_dict(),
            "periods": {},
        }
        family_skills: dict[tuple[str, str], float] = {}
        challenger_cells: dict[tuple[str, str, int, str], Mapping[str, object]] = {}
        for period in OOS_PERIOD_KEYS:
            period_report: dict[str, object] = {}
            for label_family in LABEL_FAMILIES:
                family_report: dict[str, object] = {"cells": {}}
                point_skills: list[float] = []
                cell_skill_draws: list[np.ndarray] = []
                for horizon in HORIZONS:
                    rows = all_rows[period][horizon][label_family]
                    bundle = state.bundle(label_family, horizon)
                    support = population.support(period, horizon, label_family)
                    assert_ordered_support_identity(
                        tuple(row.timestamp for row in rows),
                        support.m0_flow_timestamps,
                        context=f"score/{period}/{label_family}/{horizon}",
                    )
                    common_probabilities = bundle.m0_common_model.predict_proba(
                        _feature_matrix(rows, "M0_COMMON"), column_names=M0_COLUMNS
                    )
                    flow_probabilities = bundle.m0_flow_model.predict_proba(
                        _feature_matrix(rows, "M0_FLOW"), column_names=M0_FLOW_COLUMNS
                    )
                    for direction in DIRECTIONS:
                        common_point, common_context = _rung_point(
                            rows=rows,
                            probabilities=common_probabilities,
                            bundle=bundle,
                            rung="M0_COMMON",
                            direction=direction,
                            cluster_lookup=cluster_lookup,
                        )
                        flow_point, flow_context = _rung_point(
                            rows=rows,
                            probabilities=flow_probabilities,
                            bundle=bundle,
                            rung="M0_FLOW",
                            direction=direction,
                            cluster_lookup=cluster_lookup,
                        )
                        common_bootstrap, common_briers = _bootstrap_rung(
                            common_context, draws
                        )
                        flow_bootstrap, flow_briers = _bootstrap_rung(flow_context, draws)
                        skill = relative_brier_skill(
                            float(flow_point["brier_score"]),
                            float(common_point["brier_score"]),
                        )
                        if skill is None:
                            raise BlockedFlowEvaluationError(
                                "paired relative Brier skill is undefined"
                            )
                        skill_draws = paired_brier_skill_draws(
                            common_briers, flow_briers
                        )
                        skill_summary = _summary(
                            skill_draws,
                            requested_draws=draws.draws,
                            undefined_key="undefined_draws_skill",
                        )
                        if skill_summary is None:
                            raise BlockedFlowEvaluationError(
                                "paired relative Brier bootstrap is undefined"
                            )
                        common_point["bootstrap"] = common_bootstrap
                        flow_point["bootstrap"] = flow_bootstrap
                        common_point["slices"] = _slices(
                            rows=rows,
                            context=common_context,
                            rv_cutpoints=bundle.rv_tertile_cutpoints,
                        )
                        flow_point["slices"] = _slices(
                            rows=rows,
                            context=flow_context,
                            rv_cutpoints=bundle.rv_tertile_cutpoints,
                        )
                        cell_key = f"{horizon // 3600}h_{direction.value.lower()}"
                        family_report["cells"][cell_key] = {
                            "support_identifier": support.m0_common_support_identifier,
                            "support_row_count": support.count,
                            "M0_COMMON": common_point,
                            "M0_FLOW": flow_point,
                            "m0_flow_relative_brier_skill_vs_m0_common": skill,
                            "paired_relative_brier_skill_bootstrap": skill_summary,
                        }
                        point_skills.append(skill)
                        cell_skill_draws.append(skill_draws)
                        challenger_cells[
                            (period, label_family, horizon, direction.value)
                        ] = flow_point
                family_skill = float(np.mean(point_skills))
                stacked = np.vstack(cell_skill_draws)
                valid = np.all(np.isfinite(stacked), axis=0)
                family_draw_values = np.mean(stacked[:, valid], axis=0)
                if family_draw_values.size == 0:
                    raise BlockedFlowEvaluationError("family paired bootstrap is undefined")
                family_report["family_relative_brier_skill"] = family_skill
                family_report["family_skill_bootstrap"] = {
                    **summarize_bootstrap(family_draw_values).to_dict(),
                    "requested_draws": draws.draws,
                    "undefined_draws": draws.draws - int(family_draw_values.size),
                    "formula": "mean of four per-draw paired Brier ratios",
                }
                family_report["news"] = NEWS_STATUS
                family_skills[(period, label_family)] = family_skill
                period_report[label_family] = family_report
            report["periods"][period] = period_report

        report["disposition"] = mechanical_disposition(
            family_skills, challenger_cells
        )
        report["disposition_rule"] = {
            "integrity_failure": "BLOCKED",
            "pass_family_skill_min_every_period_and_family": PASS_SKILL,
            "fail_family_skill_max_both_families_all_periods": FAIL_SKILL,
            "alert_gates_apply_to": "M0_FLOW",
            "precision_multiple": PRECISION_MULTIPLE,
            "cluster_recall_min": PASS_RECALL,
            "lead_seconds_by_horizon": {
                str(key): value for key, value in LEAD_GATES.items()
            },
            "eligible_clusters_min": MIN_CLUSTERS,
            "otherwise": "NULL",
            "pooled_fixed_only_slice_coefficient_bootstrap_or_subjective_rescue": False,
        }
        return report
    except (BlockedModelError, BlockedSupportError) as error:
        raise BlockedFlowEvaluationError(str(error)) from error


fit_exp005_flow = fit_flow_models
evaluate_exp005_flow = evaluate_flow_models
fit_flow = fit_flow_models
evaluate_flow = evaluate_flow_models
fit_exp005 = fit_flow_models
evaluate_exp005 = evaluate_flow_models
