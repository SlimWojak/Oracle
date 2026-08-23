import importlib.util
import sys
import unittest
from pathlib import Path


def load_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "build_challenger_history.py"
    spec = importlib.util.spec_from_file_location("build_challenger_history", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module from {script_path}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec: dataclass field-type resolution consults sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


history = load_module()

# Epochs: 2021-06-01 -> 1622505600, 2022-01-10 -> 1641772800, 2024-03-05 -> 1709596800
FAKE_CLUSTERS = {
    "horizons": [
        {
            "horizon_bars": 60,
            "horizon_seconds": 3600,
            "clusters": [
                {
                    "start_timestamp": 1622505600,
                    "start": "2021-06-01T00:00:00Z",
                    "direction": "up",
                },
                {
                    "start_timestamp": 1641772800,
                    "start": "2022-01-10T00:00:00Z",
                    "direction": "down",
                },
                {
                    "start_timestamp": 1709596800,
                    "start": "2024-03-05T00:00:00Z",
                    "direction": "mixed",
                },
            ],
        }
    ]
}


class WindowStatsTests(unittest.TestCase):
    def test_straddler_exclusion_and_counts(self) -> None:
        payload = history.build_payload(FAKE_CLUSTERS)
        windows = payload["horizons"][0]["windows"]
        self.assertEqual(windows["price_controls"]["total"], 3)
        # cex_inferred starts 2021-12-01: the 2021-06 cluster is excluded.
        self.assertEqual(windows["cex_inferred"]["total"], 2)
        self.assertEqual(windows["cex_inferred"]["down"], 1)
        self.assertEqual(windows["cex_inferred"]["mixed"], 1)
        self.assertEqual(windows["cex_inferred"]["first_cluster"], "2022-01-10T00:00:00Z")
        # hl_impact_context starts 2023-05-20: only the 2024 cluster remains.
        self.assertEqual(windows["hl_impact_context"]["total"], 1)
        self.assertEqual(windows["hl_impact_context"]["per_year"], {"2024": 1})
        # hl_fills starts 2025-05-25: nothing qualifies.
        self.assertEqual(windows["hl_fills"]["total"], 0)
        self.assertIsNone(windows["hl_fills"]["first_cluster"])

    def test_markdown_renders_all_windows(self) -> None:
        payload = history.build_payload(FAKE_CLUSTERS)
        text = history.render_markdown(payload)
        for window in history.WINDOWS:
            self.assertIn(window.start, text)
        self.assertIn("Vendor/model challenger", text)


if __name__ == "__main__":
    unittest.main()
