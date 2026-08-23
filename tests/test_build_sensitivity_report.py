import importlib.util
import sys
import unittest
from pathlib import Path


def load_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "build_sensitivity_report.py"
    spec = importlib.util.spec_from_file_location("build_sensitivity_report", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module from {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sensitivity = load_module()


def cluster(start: int, end: int, direction: str) -> dict[str, object]:
    return {"start_timestamp": start, "end_timestamp": end, "direction": direction}


class MatchClustersTests(unittest.TestCase):
    def test_retained_removed_added(self) -> None:
        old = [cluster(0, 100, "up"), cluster(1000, 1100, "down")]
        new = [cluster(10, 90, "up"), cluster(5000, 5100, "up")]
        churn = sensitivity.match_clusters(old, new)
        self.assertEqual(churn["retained"], 1)
        self.assertEqual(churn["removed"], 1)
        self.assertEqual(churn["added"], 1)
        self.assertEqual(churn["direction_changed"], 0)

    def test_direction_flip_detected(self) -> None:
        old = [cluster(0, 100, "up")]
        new = [cluster(0, 100, "down")]
        churn = sensitivity.match_clusters(old, new)
        self.assertEqual(churn["direction_changed"], 1)
        self.assertEqual(churn["retained"], 0)

    def test_mixed_is_compatible_with_pure(self) -> None:
        old = [cluster(0, 100, "up")]
        new = [cluster(0, 100, "mixed")]
        churn = sensitivity.match_clusters(old, new)
        self.assertEqual(churn["retained"], 1)
        self.assertEqual(churn["pure_to_mixed"], 1)

    def test_best_overlap_wins_and_start_delta(self) -> None:
        old = [cluster(100, 400, "up")]
        new = [cluster(80, 150, "down"), cluster(160, 500, "up")]
        churn = sensitivity.match_clusters(old, new)
        # The larger overlap (160..400) is the match; delta = 60.
        self.assertEqual(churn["retained"], 1)
        self.assertEqual(churn["start_delta_seconds"]["median_abs"], 60.0)
        self.assertEqual(churn["added"], 0)

    def test_touching_but_not_overlapping_is_removed(self) -> None:
        old = [cluster(0, 100, "up")]
        new = [cluster(100, 200, "up")]
        churn = sensitivity.match_clusters(old, new)
        self.assertEqual(churn["removed"], 1)
        self.assertEqual(churn["added"], 1)


if __name__ == "__main__":
    unittest.main()
