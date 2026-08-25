"""Frozen estimator and probability-metric primitives for EXP-004 M0.

This module deliberately has no knowledge of outcomes beyond the three scored
causes, period splits, event clusters, alert episodes, or rung dispositions.
Those research-semantic concerns belong to the EXP-004 evaluation layer.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

RIDGE_PENALTY = 1e-4
OPTIMIZER_MAXITER = 2_000
OPTIMIZER_FTOL = 1e-12
OPTIMIZER_GTOL = 1e-8
FINAL_GRADIENT_TOLERANCE = 1e-6
PROBABILITY_SUM_TOLERANCE = 1e-12
CALIBRATION_CLIP = 1e-6
BOOTSTRAP_DRAWS = 1_000
BOOTSTRAP_SEED = 20_250_825

CAUSES = ("UP", "DOWN", "NONE")
_CAUSE_TO_INDEX = {cause: index for index, cause in enumerate(CAUSES)}


class BlockedModelError(RuntimeError):
    """Raised when a frozen model-integrity requirement is not satisfied."""


def _matrix(values: Sequence[Sequence[float]] | np.ndarray, *, name: str) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 2:
        raise BlockedModelError(f"{name} must be a two-dimensional matrix")
    if array.shape[0] == 0 or array.shape[1] == 0:
        raise BlockedModelError(f"{name} must be non-empty")
    if not np.all(np.isfinite(array)):
        raise BlockedModelError(f"{name} contains nonfinite values")
    return array


def _column_names(names: Sequence[str], width: int) -> tuple[str, ...]:
    frozen = tuple(str(name) for name in names)
    if len(frozen) != width:
        raise BlockedModelError(
            f"column-name count {len(frozen)} does not match matrix width {width}"
        )
    if any(not name for name in frozen):
        raise BlockedModelError("column names must be non-empty")
    if len(set(frozen)) != len(frozen):
        raise BlockedModelError("column names must be unique")
    return frozen


def _encoded_causes(causes: Sequence[str | int] | np.ndarray, rows: int) -> np.ndarray:
    raw = np.asarray(causes)
    if raw.ndim != 1 or raw.shape[0] != rows:
        raise BlockedModelError("cause vector must have one entry per feature row")
    encoded = np.empty(rows, dtype=np.int64)
    for index, value in enumerate(raw.tolist()):
        if isinstance(value, str):
            key = value.upper()
            if key not in _CAUSE_TO_INDEX:
                raise BlockedModelError(f"unsupported scored cause: {value!r}")
            encoded[index] = _CAUSE_TO_INDEX[key]
        elif isinstance(value, (int, np.integer)) and int(value) in range(3):
            encoded[index] = int(value)
        else:
            raise BlockedModelError(f"unsupported scored cause: {value!r}")
    return encoded


@dataclass(frozen=True)
class DevelopmentStandardizer:
    """Development-only population standardization frozen for OOS use."""

    column_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]

    @classmethod
    def fit(
        cls,
        values: Sequence[Sequence[float]] | np.ndarray,
        column_names: Sequence[str],
    ) -> DevelopmentStandardizer:
        matrix = _matrix(values, name="development predictors")
        names = _column_names(column_names, matrix.shape[1])
        means = np.mean(matrix, axis=0)
        scales = np.std(matrix, axis=0, ddof=0)
        if not np.all(np.isfinite(means)):
            raise BlockedModelError("development predictor means are nonfinite")
        if not np.all(np.isfinite(scales)) or np.any(scales == 0.0):
            raise BlockedModelError("development predictor deviation is zero or nonfinite")
        return cls(
            column_names=names,
            means=tuple(float(value) for value in means),
            scales=tuple(float(value) for value in scales),
        )

    def transform(
        self,
        values: Sequence[Sequence[float]] | np.ndarray,
        *,
        column_names: Sequence[str] | None = None,
    ) -> np.ndarray:
        matrix = _matrix(values, name="predictors")
        if matrix.shape[1] != len(self.column_names):
            raise BlockedModelError("predictor width does not match frozen scaler")
        if column_names is not None and tuple(column_names) != self.column_names:
            raise BlockedModelError("predictor column order does not match frozen scaler")
        means = np.asarray(self.means, dtype=np.float64)
        scales = np.asarray(self.scales, dtype=np.float64)
        standardized = (matrix - means) / scales
        if not np.all(np.isfinite(standardized)):
            raise BlockedModelError("standardized predictors are nonfinite")
        return standardized

    def to_dict(self) -> dict[str, object]:
        return {
            "column_names": list(self.column_names),
            "means": list(self.means),
            "population_scales_ddof0": list(self.scales),
        }


def stable_joint_probabilities(logits: Sequence[Sequence[float]] | np.ndarray) -> np.ndarray:
    """Return stable ``(p_up, p_down, p_none)`` from two finite logits."""

    eta = np.asarray(logits, dtype=np.float64)
    if eta.ndim != 2 or eta.shape[1] != 2:
        raise BlockedModelError("joint logits must have shape (n, 2)")
    if not np.all(np.isfinite(eta)):
        raise BlockedModelError("joint logits contain nonfinite values")
    reference = np.zeros((eta.shape[0], 1), dtype=np.float64)
    all_logits = np.concatenate((eta, reference), axis=1)
    row_max = np.max(all_logits, axis=1, keepdims=True)
    shifted = np.exp(all_logits - row_max)
    probabilities = shifted / np.sum(shifted, axis=1, keepdims=True)
    validate_joint_probabilities(probabilities)
    return probabilities


def validate_joint_probabilities(probabilities: np.ndarray) -> None:
    """Apply the frozen EXP-004 joint-probability integrity checks."""

    values = np.asarray(probabilities, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 3:
        raise BlockedModelError("joint probabilities must have shape (n, 3)")
    if not np.all(np.isfinite(values)):
        raise BlockedModelError("joint probabilities contain nonfinite values")
    if np.any(values < 0.0) or np.any(values > 1.0):
        raise BlockedModelError("joint probabilities fall outside [0, 1]")
    sums = np.sum(values, axis=1)
    if np.any(np.abs(sums - 1.0) > PROBABILITY_SUM_TOLERANCE):
        raise BlockedModelError("joint probabilities do not sum to one within 1e-12")


def multinomial_objective_gradient(
    parameters: Sequence[float] | np.ndarray,
    standardized_predictors: Sequence[Sequence[float]] | np.ndarray,
    encoded_causes: Sequence[int] | np.ndarray,
    *,
    ridge: float = RIDGE_PENALTY,
) -> tuple[float, np.ndarray]:
    """Return the exact mean-NLL plus slopes-only ridge objective and gradient."""

    predictors = _matrix(standardized_predictors, name="standardized predictors")
    causes = _encoded_causes(encoded_causes, predictors.shape[0])
    if not math.isfinite(ridge) or ridge < 0.0:
        raise BlockedModelError("ridge penalty must be finite and nonnegative")
    expected_size = 2 * (predictors.shape[1] + 1)
    theta = np.asarray(parameters, dtype=np.float64)
    if theta.ndim != 1 or theta.shape[0] != expected_size:
        raise BlockedModelError(f"parameter vector must have length {expected_size}")
    if not np.all(np.isfinite(theta)):
        raise BlockedModelError("parameter vector contains nonfinite values")

    coefficient_matrix = theta.reshape(2, predictors.shape[1] + 1)
    intercepts = coefficient_matrix[:, 0]
    slopes = coefficient_matrix[:, 1:]
    logits = predictors @ slopes.T + intercepts

    reference = np.zeros((logits.shape[0], 1), dtype=np.float64)
    all_logits = np.concatenate((logits, reference), axis=1)
    row_max = np.max(all_logits, axis=1)
    log_denominator = row_max + np.log(
        np.sum(np.exp(all_logits - row_max[:, np.newaxis]), axis=1)
    )
    selected_logits = all_logits[np.arange(causes.shape[0]), causes]
    mean_nll = float(np.mean(log_denominator - selected_logits))
    penalty = 0.5 * ridge * float(np.sum(slopes * slopes))
    objective = mean_nll + penalty

    probabilities = np.exp(logits - log_denominator[:, np.newaxis])
    residual = probabilities
    residual[np.arange(causes.shape[0]), np.minimum(causes, 1)] -= (causes < 2).astype(
        np.float64
    )
    gradient = np.empty_like(coefficient_matrix)
    gradient[:, 0] = np.mean(residual, axis=0)
    gradient[:, 1:] = residual.T @ predictors / predictors.shape[0] + ridge * slopes
    flat_gradient = gradient.reshape(-1)
    if not math.isfinite(objective) or not np.all(np.isfinite(flat_gradient)):
        raise BlockedModelError("model objective or gradient is nonfinite")
    return objective, flat_gradient


@dataclass(frozen=True)
class FrozenMultinomialState:
    """Immutable M0 fit state applied unchanged outside development."""

    support_identifier: str
    standardizer: DevelopmentStandardizer
    intercepts_up_down: tuple[float, float]
    slopes_up_down: tuple[tuple[float, ...], tuple[float, ...]]
    ridge_penalty: float
    objective: float
    final_gradient_infinity_norm: float
    iterations: int

    @property
    def column_names(self) -> tuple[str, ...]:
        return self.standardizer.column_names

    def predict_proba(
        self,
        values: Sequence[Sequence[float]] | np.ndarray,
        *,
        column_names: Sequence[str] | None = None,
    ) -> np.ndarray:
        standardized = self.standardizer.transform(values, column_names=column_names)
        slopes = np.asarray(self.slopes_up_down, dtype=np.float64)
        intercepts = np.asarray(self.intercepts_up_down, dtype=np.float64)
        logits = standardized @ slopes.T + intercepts
        return stable_joint_probabilities(logits)

    def to_dict(self) -> dict[str, object]:
        return {
            "support_identifier": self.support_identifier,
            "causes_in_probability_order": list(CAUSES),
            "none_is_reference": True,
            "standardizer": self.standardizer.to_dict(),
            "intercepts_up_down": list(self.intercepts_up_down),
            "slopes_up_down": [list(row) for row in self.slopes_up_down],
            "ridge_penalty_slopes_only": self.ridge_penalty,
            "objective": self.objective,
            "final_gradient_infinity_norm": self.final_gradient_infinity_norm,
            "optimizer": {
                "method": "L-BFGS-B",
                "initialization": "all_zero",
                "maxiter": OPTIMIZER_MAXITER,
                "ftol": OPTIMIZER_FTOL,
                "gtol": OPTIMIZER_GTOL,
                "iterations": self.iterations,
            },
        }


def fit_frozen_multinomial(
    development_predictors: Sequence[Sequence[float]] | np.ndarray,
    development_causes: Sequence[str | int] | np.ndarray,
    *,
    column_names: Sequence[str],
    support_identifier: str,
) -> FrozenMultinomialState:
    """Fit the frozen deterministic baseline-category multinomial estimator."""

    if not support_identifier:
        raise BlockedModelError("development support identifier must be non-empty")
    predictors = _matrix(development_predictors, name="development predictors")
    causes = _encoded_causes(development_causes, predictors.shape[0])
    standardizer = DevelopmentStandardizer.fit(predictors, column_names)
    standardized = standardizer.transform(predictors)
    initial = np.zeros(2 * (predictors.shape[1] + 1), dtype=np.float64)

    try:
        from scipy.optimize import minimize
    except ImportError as error:  # pragma: no cover - deployment integrity path
        raise BlockedModelError("SciPy is required for the frozen L-BFGS-B estimator") from error

    result = minimize(
        multinomial_objective_gradient,
        initial,
        args=(standardized, causes),
        method="L-BFGS-B",
        jac=True,
        options={
            "maxiter": OPTIMIZER_MAXITER,
            "ftol": OPTIMIZER_FTOL,
            "gtol": OPTIMIZER_GTOL,
        },
    )
    if not bool(result.success):
        raise BlockedModelError(f"L-BFGS-B did not converge: {result.message}")
    coefficients = np.asarray(result.x, dtype=np.float64)
    if not np.all(np.isfinite(coefficients)):
        raise BlockedModelError("L-BFGS-B returned nonfinite coefficients")
    objective, gradient = multinomial_objective_gradient(coefficients, standardized, causes)
    gradient_norm = float(np.max(np.abs(gradient)))
    if not math.isfinite(gradient_norm) or gradient_norm > FINAL_GRADIENT_TOLERANCE:
        raise BlockedModelError(
            "L-BFGS-B final gradient infinity norm exceeds frozen 1e-6 tolerance"
        )
    matrix = coefficients.reshape(2, predictors.shape[1] + 1)
    state = FrozenMultinomialState(
        support_identifier=support_identifier,
        standardizer=standardizer,
        intercepts_up_down=(float(matrix[0, 0]), float(matrix[1, 0])),
        slopes_up_down=(
            tuple(float(value) for value in matrix[0, 1:]),
            tuple(float(value) for value in matrix[1, 1:]),
        ),
        ridge_penalty=RIDGE_PENALTY,
        objective=objective,
        final_gradient_infinity_norm=gradient_norm,
        iterations=int(result.nit),
    )
    state.predict_proba(predictors, column_names=column_names)
    return state


@dataclass(frozen=True)
class CalibrationDiagnostic:
    intercept: float
    slope: float

    def to_dict(self) -> dict[str, float]:
        return {"intercept": self.intercept, "slope": self.slope}


def _binary_logistic_objective_gradient(
    parameters: np.ndarray,
    design: np.ndarray,
    targets: np.ndarray,
) -> tuple[float, np.ndarray]:
    linear = design @ parameters
    objective = float(np.mean(np.logaddexp(0.0, linear) - targets * linear))
    probabilities = np.empty_like(linear)
    nonnegative = linear >= 0.0
    probabilities[nonnegative] = 1.0 / (1.0 + np.exp(-linear[nonnegative]))
    exp_linear = np.exp(linear[~nonnegative])
    probabilities[~nonnegative] = exp_linear / (1.0 + exp_linear)
    gradient = design.T @ (probabilities - targets) / targets.shape[0]
    return objective, gradient


def calibration_diagnostic(
    targets: Sequence[int] | np.ndarray,
    probabilities: Sequence[float] | np.ndarray,
) -> CalibrationDiagnostic | None:
    """Fit the frozen unpenalized ``Y ~ 1 + logit(p)`` diagnostic.

    Probabilities are clipped only inside this diagnostic. Undefined inputs or
    a diagnostic without both outcome classes or predictor variation return
    ``None`` rather than manufacturing a value.
    """

    y = np.asarray(targets, dtype=np.float64)
    p = np.asarray(probabilities, dtype=np.float64)
    if y.ndim != 1 or p.ndim != 1 or y.shape != p.shape or y.size == 0:
        return None
    if not np.all(np.isfinite(y)) or not np.all(np.isfinite(p)):
        return None
    if np.any(p < 0.0) or np.any(p > 1.0):
        return None
    if np.any((y != 0.0) & (y != 1.0)) or np.unique(y).size != 2:
        return None
    clipped = np.clip(p, CALIBRATION_CLIP, 1.0 - CALIBRATION_CLIP)
    logit = np.log(clipped / (1.0 - clipped))
    if not np.all(np.isfinite(logit)) or float(np.std(logit, ddof=0)) == 0.0:
        return None
    design = np.column_stack((np.ones(y.shape[0], dtype=np.float64), logit))

    try:
        from scipy.optimize import minimize
    except ImportError:  # pragma: no cover - deployment integrity path
        return None
    result = minimize(
        _binary_logistic_objective_gradient,
        np.zeros(2, dtype=np.float64),
        args=(design, y),
        method="L-BFGS-B",
        jac=True,
        options={
            "maxiter": OPTIMIZER_MAXITER,
            "ftol": OPTIMIZER_FTOL,
            "gtol": OPTIMIZER_GTOL,
        },
    )
    if not bool(result.success):
        return None
    coefficients = np.asarray(result.x, dtype=np.float64)
    if not np.all(np.isfinite(coefficients)):
        return None
    _objective, gradient = _binary_logistic_objective_gradient(coefficients, design, y)
    if float(np.max(np.abs(gradient))) > FINAL_GRADIENT_TOLERANCE:
        return None
    return CalibrationDiagnostic(intercept=float(coefficients[0]), slope=float(coefficients[1]))


@dataclass(frozen=True)
class DirectionalProbabilityMetrics:
    count: int
    brier_score: float
    event_rate: float
    mean_probability: float
    calibration: CalibrationDiagnostic | None

    def to_dict(self) -> dict[str, object]:
        return {
            "count": self.count,
            "brier_score": self.brier_score,
            "event_rate": self.event_rate,
            "mean_probability": self.mean_probability,
            "calibration_intercept": (
                None if self.calibration is None else self.calibration.intercept
            ),
            "calibration_slope": None if self.calibration is None else self.calibration.slope,
        }


def directional_probability_metrics(
    targets: Sequence[int] | np.ndarray,
    probabilities: Sequence[float] | np.ndarray,
) -> DirectionalProbabilityMetrics:
    """Compute equal-row-weight directional probability metrics."""

    y = np.asarray(targets, dtype=np.float64)
    p = np.asarray(probabilities, dtype=np.float64)
    if y.ndim != 1 or p.ndim != 1 or y.shape != p.shape or y.size == 0:
        raise ValueError("targets and probabilities must be matching non-empty vectors")
    if not np.all(np.isfinite(y)) or np.any((y != 0.0) & (y != 1.0)):
        raise ValueError("targets must be finite binary values")
    if not np.all(np.isfinite(p)) or np.any(p < 0.0) or np.any(p > 1.0):
        raise ValueError("probabilities must be finite values in [0, 1]")
    return DirectionalProbabilityMetrics(
        count=int(y.shape[0]),
        brier_score=float(np.mean((p - y) ** 2)),
        event_rate=float(np.mean(y)),
        mean_probability=float(np.mean(p)),
        calibration=calibration_diagnostic(y, p),
    )


def relative_brier_skill(model_brier: float, preceding_brier: float) -> float | None:
    """Return ``1 - BS_model / BS_preceding`` or ``None`` when undefined."""

    if not math.isfinite(model_brier) or not math.isfinite(preceding_brier):
        return None
    if model_brier < 0.0 or preceding_brier <= 0.0:
        return None
    return float(1.0 - model_brier / preceding_brier)


def development_alert_threshold(probabilities: Sequence[float] | np.ndarray) -> float:
    """Freeze the development 99th percentile using ``method='higher'``."""

    values = np.asarray(probabilities, dtype=np.float64)
    if values.ndim != 1 or values.size == 0:
        raise ValueError("development probabilities must be a non-empty vector")
    if not np.all(np.isfinite(values)) or np.any(values < 0.0) or np.any(values > 1.0):
        raise ValueError("development probabilities must lie in [0, 1]")
    return float(np.quantile(values, 0.99, method="higher"))


def strict_alerts(
    probabilities: Sequence[float] | np.ndarray,
    threshold: float,
) -> np.ndarray:
    """Apply the frozen strict ``p > threshold`` alert rule."""

    values = np.asarray(probabilities, dtype=np.float64)
    if values.ndim != 1 or not np.all(np.isfinite(values)):
        raise ValueError("probabilities must be a finite vector")
    if np.any(values < 0.0) or np.any(values > 1.0):
        raise ValueError("probabilities must lie in [0, 1]")
    if not math.isfinite(threshold) or threshold < 0.0 or threshold > 1.0:
        raise ValueError("alert threshold must lie in [0, 1]")
    return values > threshold


def utc_week_start(timestamp: int) -> int:
    """Return Monday 00:00:00Z epoch seconds for an integer UTC timestamp."""

    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, np.integer)):
        raise ValueError("timestamp must be integer epoch seconds")
    day = int(timestamp) // 86_400
    weekday = (day + 3) % 7  # 1970-01-01 was Thursday when Monday is zero.
    return (day - weekday) * 86_400


def utc_week_ids(timestamps: Sequence[int] | np.ndarray) -> np.ndarray:
    """Vectorize :func:`utc_week_start` for UTC epoch-second timestamps."""

    values = np.asarray(timestamps)
    if values.ndim != 1:
        raise ValueError("timestamps must be a vector")
    return np.asarray([utc_week_start(value) for value in values.tolist()], dtype=np.int64)


@dataclass(frozen=True)
class WeekBootstrapDraws:
    """One family-wide set of sampled UTC-week multiplicities."""

    seed: int
    draws: int
    weeks: tuple[int, ...]
    week_multiplicities: np.ndarray

    def index_multiplicities(self, object_week_ids: Sequence[int] | np.ndarray) -> np.ndarray:
        """Map the same family draw onto rows, episodes, or whole clusters."""

        object_weeks = np.asarray(object_week_ids, dtype=np.int64)
        if object_weeks.ndim != 1:
            raise ValueError("object week ids must be a vector")
        positions = {week: index for index, week in enumerate(self.weeks)}
        try:
            columns = [positions[int(week)] for week in object_weeks.tolist()]
        except KeyError as error:
            raise ValueError(
                f"object week {error.args[0]} is outside bootstrap universe"
            ) from error
        return self.week_multiplicities[:, columns].copy()

    def to_dict(self) -> dict[str, object]:
        return {
            "seed": self.seed,
            "draws": self.draws,
            "weeks": list(self.weeks),
            "week_multiplicities": self.week_multiplicities.tolist(),
        }


def draw_week_bootstrap_multiplicities(
    family_week_ids: Sequence[int] | np.ndarray,
    *,
    draws: int = BOOTSTRAP_DRAWS,
    seed: int = BOOTSTRAP_SEED,
) -> WeekBootstrapDraws:
    """Draw UTC weeks with replacement once for the entire linked family."""

    values = np.asarray(family_week_ids, dtype=np.int64)
    if values.ndim != 1 or values.size == 0:
        raise ValueError("family week ids must be a non-empty vector")
    if draws <= 0:
        raise ValueError("bootstrap draws must be positive")
    weeks = np.unique(values)
    rng = np.random.default_rng(seed)
    multiplicities = np.empty((draws, weeks.shape[0]), dtype=np.int64)
    for draw_index in range(draws):
        sampled = rng.choice(weeks, size=weeks.shape[0], replace=True)
        positions = np.searchsorted(weeks, sampled)
        multiplicities[draw_index] = np.bincount(positions, minlength=weeks.shape[0])
    return WeekBootstrapDraws(
        seed=seed,
        draws=draws,
        weeks=tuple(int(value) for value in weeks),
        week_multiplicities=multiplicities,
    )


@dataclass(frozen=True)
class BootstrapSummary:
    count: int
    standard_error_ddof1: float | None
    percentile_95_interval: tuple[float, float] | None

    def to_dict(self) -> dict[str, object]:
        return {
            "count": self.count,
            "standard_error_ddof1": self.standard_error_ddof1,
            "percentile_95_interval": (
                None
                if self.percentile_95_interval is None
                else list(self.percentile_95_interval)
            ),
        }


def summarize_bootstrap(values: Sequence[float] | np.ndarray) -> BootstrapSummary:
    """Summarize finite bootstrap statistics with ddof=1 and percentile bounds."""

    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or array.size == 0:
        raise ValueError("bootstrap statistics must be a non-empty vector")
    if not np.all(np.isfinite(array)):
        raise ValueError("bootstrap statistics must all be finite")
    standard_error = float(np.std(array, ddof=1)) if array.size > 1 else None
    interval = (
        float(np.percentile(array, 2.5)),
        float(np.percentile(array, 97.5)),
    )
    return BootstrapSummary(
        count=int(array.size),
        standard_error_ddof1=standard_error,
        percentile_95_interval=interval,
    )
