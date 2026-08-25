from __future__ import annotations

import math
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from oracle_research.exp004_m0_model import (
    BOOTSTRAP_DRAWS,
    BOOTSTRAP_SEED,
    BlockedModelError,
    DevelopmentStandardizer,
    calibration_diagnostic,
    development_alert_threshold,
    directional_probability_metrics,
    draw_week_bootstrap_multiplicities,
    fit_frozen_multinomial,
    multinomial_objective_gradient,
    relative_brier_skill,
    stable_joint_probabilities,
    strict_alerts,
    summarize_bootstrap,
    utc_week_ids,
    utc_week_start,
    validate_joint_probabilities,
)


def timestamp(year: int, month: int, day: int, hour: int = 0) -> int:
    return int(datetime(year, month, day, hour, tzinfo=UTC).timestamp())


class StandardizerTests(unittest.TestCase):
    def test_population_scaler_and_frozen_column_order(self) -> None:
        values = np.asarray([[1.0, 10.0], [2.0, 13.0], [3.0, 16.0]])
        scaler = DevelopmentStandardizer.fit(values, ("first", "second"))

        np.testing.assert_allclose(scaler.means, [2.0, 13.0])
        np.testing.assert_allclose(scaler.scales, np.std(values, axis=0, ddof=0))
        np.testing.assert_allclose(
            scaler.transform(values, column_names=("first", "second")),
            (values - np.mean(values, axis=0)) / np.std(values, axis=0, ddof=0),
        )
        with self.assertRaisesRegex(BlockedModelError, "column order"):
            scaler.transform(values, column_names=("second", "first"))

    def test_blocks_zero_or_nonfinite_deviation(self) -> None:
        with self.assertRaisesRegex(BlockedModelError, "zero or nonfinite"):
            DevelopmentStandardizer.fit([[1.0, 2.0], [1.0, 3.0]], ("x", "y"))
        with self.assertRaisesRegex(BlockedModelError, "nonfinite"):
            DevelopmentStandardizer.fit([[1.0], [math.nan]], ("x",))


class MultinomialTests(unittest.TestCase):
    def test_stable_extreme_logits_preserve_joint_identity(self) -> None:
        probabilities = stable_joint_probabilities(
            [[1_000.0, -1_000.0], [-1_000.0, 1_000.0], [1_000.0, 1_000.0]]
        )

        np.testing.assert_allclose(np.sum(probabilities, axis=1), 1.0, atol=1e-15)
        self.assertEqual(probabilities[0, 0], 1.0)
        self.assertEqual(probabilities[1, 1], 1.0)
        np.testing.assert_allclose(probabilities[2], [0.5, 0.5, 0.0], atol=1e-15)

    def test_slopes_only_l2_excludes_intercepts(self) -> None:
        predictors = np.asarray([[-1.0], [0.0], [1.0]])
        causes = np.asarray([0, 2, 1])
        parameters = np.asarray([0.7, 2.0, -0.4, -3.0])

        unpenalized_value, unpenalized_gradient = multinomial_objective_gradient(
            parameters, predictors, causes, ridge=0.0
        )
        penalized_value, penalized_gradient = multinomial_objective_gradient(
            parameters, predictors, causes, ridge=1e-4
        )

        self.assertAlmostEqual(
            penalized_value - unpenalized_value,
            0.5 * 1e-4 * (2.0**2 + (-3.0) ** 2),
        )
        self.assertEqual(penalized_gradient[0] - unpenalized_gradient[0], 0.0)
        self.assertEqual(penalized_gradient[2] - unpenalized_gradient[2], 0.0)
        self.assertAlmostEqual(penalized_gradient[1] - unpenalized_gradient[1], 2e-4)
        self.assertAlmostEqual(penalized_gradient[3] - unpenalized_gradient[3], -3e-4)

    def test_known_synthetic_three_class_fit(self) -> None:
        predictor_rows: list[list[float]] = []
        causes: list[str] = []
        # Symmetric, nonseparated counts with UP increasing and DOWN decreasing.
        counts = {
            -2.0: (1, 14, 5),
            -1.0: (3, 10, 7),
            0.0: (6, 6, 8),
            1.0: (10, 3, 7),
            2.0: (14, 1, 5),
        }
        for value, cause_counts in counts.items():
            for cause, count in zip(("UP", "DOWN", "NONE"), cause_counts, strict=True):
                predictor_rows.extend([[value]] * count)
                causes.extend([cause] * count)

        state = fit_frozen_multinomial(
            predictor_rows,
            causes,
            column_names=("trend",),
            support_identifier="synthetic-support-sha256",
        )
        probabilities = state.predict_proba(
            [[-2.0], [0.0], [2.0]], column_names=("trend",)
        )

        self.assertGreater(state.slopes_up_down[0][0], 0.0)
        self.assertLess(state.slopes_up_down[1][0], 0.0)
        self.assertLess(probabilities[0, 0], probabilities[2, 0])
        self.assertGreater(probabilities[0, 1], probabilities[2, 1])
        np.testing.assert_allclose(np.sum(probabilities, axis=1), 1.0, atol=1e-12)
        self.assertEqual(state.to_dict()["support_identifier"], "synthetic-support-sha256")

    def test_probability_integrity_blocks_invalid_values(self) -> None:
        with self.assertRaisesRegex(BlockedModelError, "sum to one"):
            validate_joint_probabilities(np.asarray([[0.2, 0.2, 0.2]]))
        with self.assertRaisesRegex(BlockedModelError, "outside"):
            validate_joint_probabilities(np.asarray([[1.1, -0.1, 0.0]]))
        with self.assertRaisesRegex(BlockedModelError, "nonfinite"):
            stable_joint_probabilities([[0.0, math.inf]])

    def test_fit_blocks_optimizer_coefficient_and_gradient_failures(self) -> None:
        fit_args = ([[0.0], [1.0], [2.0]], ["UP", "DOWN", "NONE"])
        fit_kwargs = {"column_names": ("x",), "support_identifier": "support"}

        with (
            patch(
                "scipy.optimize.minimize",
                return_value=SimpleNamespace(success=False, message="forced failure"),
            ),
            self.assertRaisesRegex(BlockedModelError, "did not converge"),
        ):
            fit_frozen_multinomial(*fit_args, **fit_kwargs)

        with (
            patch(
                "scipy.optimize.minimize",
                return_value=SimpleNamespace(
                    success=True, x=np.full(4, math.nan), message="", nit=1
                ),
            ),
            self.assertRaisesRegex(BlockedModelError, "nonfinite coefficients"),
        ):
            fit_frozen_multinomial(*fit_args, **fit_kwargs)

        with (
            patch(
                "scipy.optimize.minimize",
                return_value=SimpleNamespace(success=True, x=np.zeros(4), message="", nit=0),
            ),
            self.assertRaisesRegex(BlockedModelError, "gradient infinity norm"),
        ):
            fit_frozen_multinomial(*fit_args, **fit_kwargs)


class MetricTests(unittest.TestCase):
    def test_directional_metrics_and_relative_skill(self) -> None:
        targets = np.asarray([0, 1, 0, 1, 1, 0], dtype=np.float64)
        probabilities = np.asarray([0.1, 0.2, 0.3, 0.5, 0.6, 0.8])
        metrics = directional_probability_metrics(targets, probabilities)

        self.assertAlmostEqual(metrics.brier_score, float(np.mean((probabilities - targets) ** 2)))
        self.assertEqual(metrics.event_rate, 0.5)
        self.assertAlmostEqual(metrics.mean_probability, float(np.mean(probabilities)))
        self.assertIsNotNone(metrics.calibration)
        self.assertAlmostEqual(relative_brier_skill(0.08, 0.1) or 0.0, 0.2)
        self.assertIsNone(relative_brier_skill(0.0, 0.0))

    def test_calibration_undefined_cases_remain_none(self) -> None:
        self.assertIsNone(calibration_diagnostic([0, 0], [0.1, 0.2]))
        self.assertIsNone(calibration_diagnostic([0, 1], [0.5, 0.5]))
        self.assertIsNone(calibration_diagnostic([0, 1], [0.1, math.nan]))
        self.assertIsNone(calibration_diagnostic([0, 1], [-0.1, 1.1]))

    def test_higher_quantile_and_strict_threshold(self) -> None:
        values = np.linspace(0.0, 1.0, 101)
        threshold = development_alert_threshold(values)

        self.assertEqual(threshold, float(np.quantile(values, 0.99, method="higher")))
        np.testing.assert_array_equal(
            strict_alerts([threshold - 0.01, threshold, 1.0], threshold),
            [False, False, True],
        )


class BootstrapTests(unittest.TestCase):
    def test_utc_week_ids_use_monday_midnight(self) -> None:
        monday = timestamp(2026, 8, 24)
        self.assertEqual(utc_week_start(timestamp(2026, 8, 24, 12)), monday)
        self.assertEqual(utc_week_start(timestamp(2026, 8, 30, 23)), monday)
        self.assertEqual(utc_week_start(timestamp(2026, 8, 31)), timestamp(2026, 8, 31))
        np.testing.assert_array_equal(
            utc_week_ids([timestamp(2026, 8, 24, 12), timestamp(2026, 8, 31)]),
            [monday, timestamp(2026, 8, 31)],
        )

    def test_seeded_family_draws_and_index_multiplicities(self) -> None:
        weeks = np.asarray([10, 10, 20, 30, 30], dtype=np.int64)
        result = draw_week_bootstrap_multiplicities(weeks, draws=3, seed=7)
        expected_rng = np.random.default_rng(7)
        expected = []
        unique = np.asarray([10, 20, 30], dtype=np.int64)
        for _ in range(3):
            sampled = expected_rng.choice(unique, size=3, replace=True)
            expected.append(np.bincount(np.searchsorted(unique, sampled), minlength=3))

        np.testing.assert_array_equal(result.week_multiplicities, expected)
        row_multiplicities = result.index_multiplicities(weeks)
        np.testing.assert_array_equal(row_multiplicities[:, 0], row_multiplicities[:, 1])
        np.testing.assert_array_equal(row_multiplicities[:, 3], row_multiplicities[:, 4])
        np.testing.assert_array_equal(row_multiplicities[:, 2], result.week_multiplicities[:, 1])

    def test_frozen_bootstrap_defaults_and_summary(self) -> None:
        result = draw_week_bootstrap_multiplicities([10, 20])
        summary = summarize_bootstrap([1.0, 2.0, 3.0, 4.0])

        self.assertEqual(result.draws, BOOTSTRAP_DRAWS)
        self.assertEqual(result.seed, BOOTSTRAP_SEED)
        self.assertAlmostEqual(summary.standard_error_ddof1 or 0.0, np.std([1, 2, 3, 4], ddof=1))
        self.assertEqual(
            summary.percentile_95_interval,
            (float(np.percentile([1, 2, 3, 4], 2.5)), float(np.percentile([1, 2, 3, 4], 97.5))),
        )


if __name__ == "__main__":
    unittest.main()
