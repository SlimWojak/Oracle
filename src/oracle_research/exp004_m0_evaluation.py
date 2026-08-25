"""Frozen fitting, reporting metrics, slices, bootstrap, and M0 disposition."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from oracle_research.exp004_m0_model import (
    BOOTSTRAP_DRAWS,
    BOOTSTRAP_SEED,
    BlockedModelError,
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
    PopulationResult,
    support_identifier,
)

DIRECTIONS = (Cause.UP, Cause.DOWN)
PASS_SKILL = 0.01
FAIL_SKILL = -0.01
PRECISION_MULTIPLE = 2.0
PASS_RECALL = 0.10
MIN_CLUSTERS = 30
LEAD_GATES = {3_600: 900.0, 14_400: 3_600.0}


class BlockedEvaluationError(RuntimeError):
    """Raised when a frozen population, metric, or bootstrap integrity gate fails."""


@dataclass(frozen=True, slots=True)
class AlertEpisode:
    start_timestamp: int
    end_timestamp: int
    contains_target: bool

    @property
    def week_start_timestamp(self) -> int:
        return utc_week_start(self.start_timestamp)


@dataclass(frozen=True, slots=True)
class ModelBundle:
    label_family: str
    horizon_seconds: int
    model: FrozenMultinomialState
    development_climatology: tuple[float, float, float]
    alert_thresholds: tuple[float, float]
    rv_tertile_cutpoints: tuple[float, float]
    development_support_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "label_family": self.label_family,
            "horizon_seconds": self.horizon_seconds,
            "model": self.model.to_dict(),
            "development_climatology_up_down_none": list(self.development_climatology),
            "alert_thresholds_up_down_strict": list(self.alert_thresholds),
            "rv_tertile_cutpoints_linear": list(self.rv_tertile_cutpoints),
            "development_support_count": self.development_support_count,
        }


@dataclass(frozen=True, slots=True)
class FrozenM0State:
    kappa: float
    bundles: tuple[ModelBundle, ...]

    def bundle(self, label_family: str, horizon_seconds: int) -> ModelBundle:
        matches = [
            bundle
            for bundle in self.bundles
            if bundle.label_family == label_family
            and bundle.horizon_seconds == horizon_seconds
        ]
        if len(matches) != 1:
            raise BlockedEvaluationError("frozen model bundle is missing or duplicated")
        return matches[0]

    def to_dict(self) -> dict[str, object]:
        return {
            "rung": "M0",
            "kappa_six_decimals": self.kappa,
            "m0_columns_ordered": list(M0_COLUMNS),
            "bundles": [bundle.to_dict() for bundle in self.bundles],
        }


def _scored_rows(
    population: PopulationResult,
    *,
    period: str,
    horizon_seconds: int,
) -> list[M0RiskRow]:
    rows = [
        row
        for row in population.rows
        if row.period == period and row.scoreable.get(horizon_seconds, False)
    ]
    if not rows:
        raise BlockedEvaluationError(
            f"empty M0 score support for {period}/{horizon_seconds}"
        )
    if any(row.features is None for row in rows):
        raise BlockedEvaluationError("score support contains an incomplete M0 row")
    return rows


def _cause_vector(
    rows: Sequence[M0RiskRow],
    label_family: str,
    horizon_seconds: int,
) -> np.ndarray:
    causes = [row.outcomes[(label_family, horizon_seconds)].cause.value for row in rows]
    if any(cause not in {"UP", "DOWN", "NONE"} for cause in causes):
        raise BlockedEvaluationError("score support contains an unscored cause")
    return np.asarray(causes)


def _feature_matrix(rows: Sequence[M0RiskRow]) -> np.ndarray:
    return np.asarray([row.features for row in rows], dtype=np.float64)


def fit_m0(population: PopulationResult) -> FrozenM0State:
    """Fit the four frozen M0 models from development support only."""

    if population.inventory.get("stage") not in {"development", "full"}:
        raise BlockedEvaluationError("population stage is invalid")
    bundles: list[ModelBundle] = []
    for horizon in HORIZONS:
        rows = _scored_rows(population, period="development", horizon_seconds=horizon)
        timestamps = [row.timestamp for row in rows]
        predictors = _feature_matrix(rows)
        rv_cutpoints = np.quantile(
            predictors[:, 2],
            [1.0 / 3.0, 2.0 / 3.0],
            method="linear",
        )
        if not bool(np.all(np.isfinite(rv_cutpoints))):
            raise BlockedEvaluationError("development RV tertiles are nonfinite")
        for label_family in LABEL_FAMILIES:
            causes = _cause_vector(rows, label_family, horizon)
            support_id = support_identifier(
                label_family=label_family,
                horizon_seconds=horizon,
                period="development",
                timestamps=timestamps,
            )
            try:
                model = fit_frozen_multinomial(
                    predictors,
                    causes,
                    column_names=M0_COLUMNS,
                    support_identifier=support_id,
                )
            except BlockedModelError as error:
                raise BlockedEvaluationError(str(error)) from error
            probabilities = model.predict_proba(predictors, column_names=M0_COLUMNS)
            climatology = tuple(
                float(np.mean(causes == cause.value))
                for cause in (Cause.UP, Cause.DOWN, Cause.NONE)
            )
            if not math.isclose(sum(climatology), 1.0, rel_tol=0.0, abs_tol=1e-12):
                raise BlockedEvaluationError("development climatology does not sum to one")
            thresholds = (
                development_alert_threshold(probabilities[:, 0]),
                development_alert_threshold(probabilities[:, 1]),
            )
            bundles.append(
                ModelBundle(
                    label_family=label_family,
                    horizon_seconds=horizon,
                    model=model,
                    development_climatology=climatology,
                    alert_thresholds=thresholds,
                    rv_tertile_cutpoints=(float(rv_cutpoints[0]), float(rv_cutpoints[1])),
                    development_support_count=len(rows),
                )
            )
    return FrozenM0State(population.kappa, tuple(bundles))


def alert_episodes(
    timestamps: Sequence[int] | np.ndarray,
    alerts: Sequence[bool] | np.ndarray,
    targets: Sequence[int] | np.ndarray,
) -> list[AlertEpisode]:
    """Group adjacent eligible hourly alerts; any missing hour closes an episode."""

    ts = np.asarray(timestamps, dtype=np.int64)
    alert_values = np.asarray(alerts, dtype=np.bool_)
    y = np.asarray(targets, dtype=np.int8)
    if ts.ndim != 1 or alert_values.shape != ts.shape or y.shape != ts.shape:
        raise ValueError("episode inputs must be aligned vectors")
    if ts.size > 1 and not bool(np.all(np.diff(ts) > 0)):
        raise ValueError("episode timestamps must be strictly increasing")
    episodes: list[AlertEpisode] = []
    current_start: int | None = None
    current_end: int | None = None
    current_positive = False
    for timestamp, alert, target in zip(
        ts.tolist(), alert_values.tolist(), y.tolist(), strict=True
    ):
        if not alert:
            continue
        if current_end is None or timestamp - current_end != 3_600:
            if current_start is not None and current_end is not None:
                episodes.append(AlertEpisode(current_start, current_end, current_positive))
            current_start = timestamp
            current_positive = False
        current_end = timestamp
        current_positive = current_positive or bool(target)
    if current_start is not None and current_end is not None:
        episodes.append(AlertEpisode(current_start, current_end, current_positive))
    return episodes


def _weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    total = int(np.sum(weights))
    if total <= 0:
        raise BlockedEvaluationError("bootstrap draw has zero applicable weight")
    return float(np.sum(values * weights) / total)


def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    positive = weights > 0
    if not bool(np.any(positive)):
        raise BlockedEvaluationError("bootstrap draw has no recalled cluster lead")
    replicated = np.repeat(values[positive], weights[positive])
    return float(np.median(replicated))


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


def _cluster_diagnostics(
    *,
    rows: Sequence[M0RiskRow],
    label_family: str,
    horizon_seconds: int,
    direction: Cause,
    alerts: np.ndarray,
    cluster_lookup: dict[str, ClusterRecord],
) -> tuple[list[str], dict[str, bool], dict[str, float], dict[str, str]]:
    eligible: dict[str, list[M0RiskRow]] = {}
    alerted: dict[str, list[M0RiskRow]] = {}
    for row, alert in zip(rows, alerts.tolist(), strict=True):
        outcome = row.outcomes[(label_family, horizon_seconds)]
        if outcome.cause is not direction:
            continue
        cluster_id = row.cluster_ids.get((label_family, horizon_seconds))
        if cluster_id is None or cluster_id not in cluster_lookup:
            raise BlockedEvaluationError("positive score row has no frozen cluster")
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
        subsequent_passages = [
            passage for passage in passage_inventory if passage >= earliest_alert
        ]
        if not subsequent_passages:
            raise BlockedEvaluationError("recalled cluster has no subsequent target passage")
        leads[cluster_id] = float(min(subsequent_passages) - earliest_alert)
    return eligible_ids, recalled, leads, morphology


def _cell_point(
    *,
    rows: Sequence[M0RiskRow],
    probabilities: np.ndarray,
    bundle: ModelBundle,
    direction: Cause,
    cluster_lookup: dict[str, ClusterRecord],
) -> tuple[dict[str, object], dict[str, object]]:
    direction_index = 0 if direction is Cause.UP else 1
    causes = _cause_vector(rows, bundle.label_family, bundle.horizon_seconds)
    targets = (causes == direction.value).astype(np.int8)
    p = probabilities[:, direction_index]
    metrics = directional_probability_metrics(targets, p)
    preceding_probability = bundle.development_climatology[direction_index]
    preceding_brier = float(np.mean((targets - preceding_probability) ** 2))
    skill = relative_brier_skill(metrics.brier_score, preceding_brier)
    if skill is None:
        raise BlockedEvaluationError("relative Brier skill is undefined")
    alerts = strict_alerts(p, bundle.alert_thresholds[direction_index])
    timestamps = np.asarray([row.timestamp for row in rows], dtype=np.int64)
    episodes = alert_episodes(timestamps, alerts, targets)
    precision = (
        float(np.mean([episode.contains_target for episode in episodes]))
        if episodes
        else None
    )
    eligible_ids, recalled, leads, morphology = _cluster_diagnostics(
        rows=rows,
        label_family=bundle.label_family,
        horizon_seconds=bundle.horizon_seconds,
        direction=direction,
        alerts=alerts,
        cluster_lookup=cluster_lookup,
    )
    recall: float | None = (
        float(np.mean([recalled[cluster_id] for cluster_id in eligible_ids]))
        if eligible_ids
        else None
    )
    lead_values = [leads[cluster_id] for cluster_id in eligible_ids if recalled[cluster_id]]
    median_lead = float(np.median(lead_values)) if lead_values else None
    point = {
        **metrics.to_dict(),
        "preceding_development_cause_rate": preceding_probability,
        "preceding_brier_score": preceding_brier,
        "relative_brier_skill": skill,
        "alert_threshold_strict_gt": bundle.alert_thresholds[direction_index],
        "alert_rows": int(np.count_nonzero(alerts)),
        "alert_share": float(np.mean(alerts)),
        "alert_episode_count": len(episodes),
        "episode_precision": precision,
        "eligible_cluster_count": len(eligible_ids),
        "cluster_recall": recall,
        "recalled_cluster_count": sum(recalled.values()),
        "median_lead_seconds": median_lead,
    }
    context = {
        "targets": targets,
        "probabilities": p,
        "preceding_probability": preceding_probability,
        "alerts": alerts,
        "timestamps": timestamps,
        "episodes": episodes,
        "eligible_cluster_ids": eligible_ids,
        "recalled": recalled,
        "leads": leads,
        "morphology": morphology,
    }
    return point, context


def _descriptive_row_slice(
    *,
    rows: Sequence[M0RiskRow],
    context: dict[str, object],
    mask: np.ndarray,
) -> dict[str, object]:
    targets = np.asarray(context["targets"])[mask]
    probabilities = np.asarray(context["probabilities"])[mask]
    alerts = np.asarray(context["alerts"])[mask]
    timestamps = np.asarray(context["timestamps"])[mask]
    if targets.size == 0:
        return {
            "row_count": 0,
            "alert_episode_count": 0,
            "eligible_cluster_count": 0,
            "interpretation": "EMPTY_REPORT_ONLY",
        }
    metrics = directional_probability_metrics(targets, probabilities)
    episodes = alert_episodes(timestamps, alerts, targets)
    label_family = str(context["label_family"])
    horizon_seconds = int(context["horizon_seconds"])
    full_targets = np.asarray(context["targets"])
    cluster_ids = {
        row.cluster_ids.get((label_family, horizon_seconds))
        for row, selected, target in zip(
            rows,
            mask.tolist(),
            full_targets.tolist(),
            strict=True,
        )
        if selected and target
    }
    cluster_ids.discard(None)
    recalled_ids: set[str] = set()
    lead_values: list[float] = []
    for cluster_id in sorted(cluster_ids):
        cluster_rows = [
            (row, bool(alert))
            for row, selected, target, alert in zip(
                rows,
                mask.tolist(),
                full_targets.tolist(),
                np.asarray(context["alerts"]).tolist(),
                strict=True,
            )
            if selected
            and target
            and row.cluster_ids.get((label_family, horizon_seconds)) == cluster_id
        ]
        alert_rows = [row for row, alert in cluster_rows if alert]
        if not alert_rows:
            continue
        recalled_ids.add(str(cluster_id))
        earliest_alert = min(row.timestamp for row in alert_rows)
        cluster_lookup = dict(context["cluster_lookup"])
        cluster = cluster_lookup[str(cluster_id)]
        direction = (
            Cause.UP
            if any(
                row.outcomes[(label_family, horizon_seconds)].cause is Cause.UP
                for row, _alert in cluster_rows
            )
            else Cause.DOWN
        )
        passage_inventory = (
            cluster.up_passage_timestamps
            if direction is Cause.UP
            else cluster.down_passage_timestamps
        )
        passages = [passage for passage in passage_inventory if passage >= earliest_alert]
        if passages:
            lead_values.append(float(min(passages) - earliest_alert))
    preceding_probability = float(context["preceding_probability"])
    preceding_brier = float(np.mean(np.square(targets - preceding_probability)))
    relative_skill = relative_brier_skill(metrics.brier_score, preceding_brier)
    return {
        **metrics.to_dict(),
        "row_count": int(targets.size),
        "preceding_brier_score": preceding_brier,
        "relative_brier_skill": relative_skill,
        "alert_rows": int(np.count_nonzero(alerts)),
        "alert_share": float(np.mean(alerts)),
        "alert_episode_count": len(episodes),
        "episode_precision": (
            float(np.mean([episode.contains_target for episode in episodes])) if episodes else 0.0
        ),
        "eligible_cluster_count": len(cluster_ids),
        "recalled_cluster_count": len(recalled_ids),
        "cluster_recall": (
            float(len(recalled_ids) / len(cluster_ids)) if cluster_ids else 0.0
        ),
        "median_lead_seconds": float(np.median(lead_values)) if lead_values else None,
        "interpretation": "REPORT_ONLY_LT30" if len(cluster_ids) < 30 else "DESCRIPTIVE",
    }


def _slices(
    *,
    rows: Sequence[M0RiskRow],
    context: dict[str, object],
    bundle: ModelBundle,
) -> dict[str, object]:
    enriched = {
        **context,
        "label_family": bundle.label_family,
        "horizon_seconds": bundle.horizon_seconds,
    }
    sigmas = np.asarray([row.sigma for row in rows], dtype=np.float64)
    vol_names = np.asarray(
        [_volatility_slice(float(sigma), bundle.rv_tertile_cutpoints) for sigma in sigmas]
    )
    session_names = np.asarray([_session(row.timestamp) for row in rows])
    volatility = {
        name: _descriptive_row_slice(
            rows=rows,
            context=enriched,
            mask=vol_names == name,
        )
        for name in ("LOW", "MID", "HIGH")
    }
    sessions = {
        name: _descriptive_row_slice(
            rows=rows,
            context=enriched,
            mask=session_names == name,
        )
        for name in ("ASIA", "EUROPE", "AMERICAS")
    }
    eligible_ids = list(context["eligible_cluster_ids"])
    recalled = dict(context["recalled"])
    leads = dict(context["leads"])
    morphology = dict(context["morphology"])
    morphology_slices: dict[str, object] = {}
    for name in ("ONE_WAY", "MIXED"):
        ids = [cluster_id for cluster_id in eligible_ids if morphology[cluster_id] == name]
        recalled_ids = [cluster_id for cluster_id in ids if recalled[cluster_id]]
        lead_values = [leads[cluster_id] for cluster_id in recalled_ids]
        morphology_slices[name] = {
            "eligible_cluster_count": len(ids),
            "recalled_cluster_count": len(recalled_ids),
            "cluster_recall": (
                float(len(recalled_ids) / len(ids)) if ids else 0.0
            ),
            "median_lead_seconds": float(np.median(lead_values)) if lead_values else None,
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
        "news": "NEWS_NOT_AVAILABLE",
    }


def _bootstrap_cell(
    *,
    point_context: dict[str, object],
    family_draws,
) -> tuple[dict[str, object], np.ndarray]:
    targets = np.asarray(point_context["targets"], dtype=np.float64)
    probabilities = np.asarray(point_context["probabilities"], dtype=np.float64)
    preceding_probability = float(point_context["preceding_probability"])
    timestamps = np.asarray(point_context["timestamps"], dtype=np.int64)
    row_weights = family_draws.index_multiplicities(utc_week_ids(timestamps))
    model_errors = np.square(probabilities - targets)
    preceding_errors = np.square(preceding_probability - targets)
    alerts = np.asarray(point_context["alerts"], dtype=np.float64)
    briers = np.full(family_draws.draws, np.nan, dtype=np.float64)
    event_rates = np.full(family_draws.draws, np.nan, dtype=np.float64)
    mean_probabilities = np.full(family_draws.draws, np.nan, dtype=np.float64)
    alert_shares = np.full(family_draws.draws, np.nan, dtype=np.float64)
    skills = np.full(family_draws.draws, np.nan, dtype=np.float64)
    calibration_intercepts = np.full(family_draws.draws, np.nan, dtype=np.float64)
    calibration_slopes = np.full(family_draws.draws, np.nan, dtype=np.float64)
    for draw in range(family_draws.draws):
        if int(np.sum(row_weights[draw])) <= 0:
            continue
        model_brier = _weighted_mean(model_errors, row_weights[draw])
        preceding_brier = _weighted_mean(preceding_errors, row_weights[draw])
        skill = relative_brier_skill(model_brier, preceding_brier)
        briers[draw] = model_brier
        event_rates[draw] = _weighted_mean(targets, row_weights[draw])
        mean_probabilities[draw] = _weighted_mean(probabilities, row_weights[draw])
        alert_shares[draw] = _weighted_mean(alerts, row_weights[draw])
        if skill is not None:
            skills[draw] = skill
        repeated_targets = np.repeat(targets, row_weights[draw])
        repeated_probabilities = np.repeat(probabilities, row_weights[draw])
        diagnostic = calibration_diagnostic(repeated_targets, repeated_probabilities)
        if diagnostic is not None:
            calibration_intercepts[draw] = diagnostic.intercept
            calibration_slopes[draw] = diagnostic.slope

    def summary(values: np.ndarray, undefined_reason: str) -> dict[str, object] | None:
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            return None
        return {
            **summarize_bootstrap(finite).to_dict(),
            "requested_draws": family_draws.draws,
            undefined_reason: family_draws.draws - int(finite.size),
        }

    episodes = list(point_context["episodes"])
    if episodes:
        episode_values = np.asarray([episode.contains_target for episode in episodes], dtype=float)
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
        precision_summary = summary(precisions, "undefined_draws_no_episode")
    else:
        precision_summary = None

    eligible_ids = list(point_context["eligible_cluster_ids"])
    recalled = dict(point_context["recalled"])
    leads = dict(point_context["leads"])
    cluster_lookup = dict(point_context["cluster_lookup"])
    if eligible_ids:
        cluster_values = np.asarray(
            [recalled[cluster_id] for cluster_id in eligible_ids],
            dtype=float,
        )
        cluster_weights = family_draws.index_multiplicities(
            [
                utc_week_start(cluster_lookup[cluster_id].start_timestamp)
                for cluster_id in eligible_ids
            ]
        )
        recalls = np.asarray(
            [
                _weighted_mean(cluster_values, cluster_weights[draw])
                if int(np.sum(cluster_weights[draw])) > 0
                else np.nan
                for draw in range(family_draws.draws)
            ]
        )
        recall_summary = summary(recalls, "undefined_draws_no_eligible_cluster")
        recalled_ids = [cluster_id for cluster_id in eligible_ids if recalled[cluster_id]]
        if recalled_ids:
            lead_values = np.asarray([leads[cluster_id] for cluster_id in recalled_ids])
            lead_weights = family_draws.index_multiplicities(
                [
                    utc_week_start(cluster_lookup[cluster_id].start_timestamp)
                    for cluster_id in recalled_ids
                ]
            )
            boot_leads = [
                _weighted_median(lead_values, lead_weights[draw])
                for draw in range(family_draws.draws)
                if int(np.sum(lead_weights[draw])) > 0
            ]
            lead_summary = summary(
                np.asarray(boot_leads, dtype=np.float64),
                "undefined_draws_no_recalled_cluster",
            )
        else:
            lead_summary = None
    else:
        recall_summary = None
        lead_summary = None
    return (
        {
            "brier_score": summary(briers, "undefined_draws_no_rows"),
            "event_rate": summary(event_rates, "undefined_draws_no_rows"),
            "mean_probability": summary(
                mean_probabilities,
                "undefined_draws_no_rows",
            ),
            "calibration_intercept": summary(
                calibration_intercepts,
                "undefined_draws_calibration",
            ),
            "calibration_slope": summary(
                calibration_slopes,
                "undefined_draws_calibration",
            ),
            "relative_brier_skill": summary(skills, "undefined_draws_skill"),
            "alert_share": summary(alert_shares, "undefined_draws_no_rows"),
            "episode_precision": precision_summary,
            "cluster_recall": recall_summary,
            "median_lead_seconds": lead_summary,
        },
        skills,
    )


def evaluate_m0(
    population: PopulationResult,
    state: FrozenM0State,
    *,
    bootstrap_draws: int = BOOTSTRAP_DRAWS,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> dict[str, object]:
    """Score each frozen OOS period once and apply the mechanical disposition."""

    if population.inventory.get("stage") != "full":
        raise BlockedEvaluationError("OOS evaluation requires a full-stage population")
    cluster_lookup = {cluster.cluster_id: cluster for cluster in population.clusters}
    report: dict[str, object] = {
        "periods": {},
        "bootstrap": {
            "block": "UTC_WEEK_FAMILY_WIDE",
            "draws": bootstrap_draws,
            "seed": bootstrap_seed,
            "se_ddof": 1,
        },
    }
    family_skills_for_disposition: dict[tuple[str, str], float] = {}
    all_cells: dict[tuple[str, str, int, str], dict[str, object]] = {}
    all_period_rows = {
        period: {
            horizon: _scored_rows(
                population,
                period=period,
                horizon_seconds=horizon,
            )
            for horizon in HORIZONS
        }
        for period in OOS_PERIOD_KEYS
    }
    family_weeks = np.unique(
        np.concatenate(
            [
                utc_week_ids([row.timestamp for row in rows])
                for period_rows in all_period_rows.values()
                for rows in period_rows.values()
            ]
        )
    )
    draws = draw_week_bootstrap_multiplicities(
        family_weeks,
        draws=bootstrap_draws,
        seed=bootstrap_seed,
    )
    for period in OOS_PERIOD_KEYS:
        period_rows = all_period_rows[period]
        period_report: dict[str, object] = {}
        for label_family in LABEL_FAMILIES:
            family_report: dict[str, object] = {"cells": {}}
            cell_skill_draws: list[np.ndarray] = []
            point_skills: list[float] = []
            for horizon in HORIZONS:
                rows = period_rows[horizon]
                bundle = state.bundle(label_family, horizon)
                probabilities = bundle.model.predict_proba(
                    _feature_matrix(rows),
                    column_names=M0_COLUMNS,
                )
                for direction in DIRECTIONS:
                    point, context = _cell_point(
                        rows=rows,
                        probabilities=probabilities,
                        bundle=bundle,
                        direction=direction,
                        cluster_lookup=cluster_lookup,
                    )
                    context["cluster_lookup"] = cluster_lookup
                    bootstrap, skill_draws = _bootstrap_cell(
                        point_context=context,
                        family_draws=draws,
                    )
                    point["bootstrap"] = bootstrap
                    point["slices"] = _slices(rows=rows, context=context, bundle=bundle)
                    cell_key = f"{horizon // 3600}h_{direction.value.lower()}"
                    family_report["cells"][cell_key] = point
                    point_skills.append(float(point["relative_brier_skill"]))
                    cell_skill_draws.append(skill_draws)
                    all_cells[(period, label_family, horizon, direction.value)] = point
            family_skill = float(np.mean(point_skills))
            stacked_skills = np.vstack(cell_skill_draws)
            family_bootstrap = np.mean(
                stacked_skills[:, np.all(np.isfinite(stacked_skills), axis=0)],
                axis=0,
            )
            family_report["family_relative_brier_skill"] = family_skill
            if family_bootstrap.size == 0:
                raise BlockedEvaluationError("family bootstrap skill is undefined")
            family_report["family_skill_bootstrap"] = {
                **summarize_bootstrap(family_bootstrap).to_dict(),
                "requested_draws": bootstrap_draws,
                "undefined_draws": bootstrap_draws - int(family_bootstrap.size),
            }
            period_report[label_family] = family_report
            family_skills_for_disposition[(period, label_family)] = family_skill
        report["periods"][period] = period_report

    fail = all(
        family_skills_for_disposition[(period, label_family)] <= FAIL_SKILL
        for period in OOS_PERIOD_KEYS
        for label_family in LABEL_FAMILIES
    )
    passed = all(
        family_skills_for_disposition[(period, label_family)] >= PASS_SKILL
        for period in OOS_PERIOD_KEYS
        for label_family in LABEL_FAMILIES
    )
    if passed:
        for period in OOS_PERIOD_KEYS:
            for label_family in LABEL_FAMILIES:
                for horizon in HORIZONS:
                    for direction in DIRECTIONS:
                        cell = all_cells[(period, label_family, horizon, direction.value)]
                        lead = cell["median_lead_seconds"]
                        precision = cell["episode_precision"]
                        recall = cell["cluster_recall"]
                        passed = passed and (
                            precision is not None
                            and float(precision)
                            >= PRECISION_MULTIPLE * float(cell["event_rate"])
                            and recall is not None
                            and float(recall) >= PASS_RECALL
                            and lead is not None
                            and float(lead) >= LEAD_GATES[horizon]
                            and int(cell["eligible_cluster_count"]) >= MIN_CLUSTERS
                        )
    disposition = "PASS" if passed else "FAIL" if fail else "NULL"
    report["disposition"] = disposition
    report["disposition_rule"] = {
        "pass_family_skill_min": PASS_SKILL,
        "fail_family_skill_max_all_periods_and_families": FAIL_SKILL,
        "precision_multiple": PRECISION_MULTIPLE,
        "cluster_recall_min": PASS_RECALL,
        "lead_seconds_by_horizon": {str(key): value for key, value in LEAD_GATES.items()},
        "eligible_clusters_min": MIN_CLUSTERS,
        "pooled_or_slice_rescue": False,
    }
    return report
