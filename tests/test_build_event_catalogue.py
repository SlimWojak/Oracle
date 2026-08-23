import importlib.util
import unittest
from pathlib import Path

import numpy as np

from oracle_research.batch_labels import batch_first_passage
from oracle_research.binance_klines import KlineArrays
from oracle_research.clusters import EventCluster
from oracle_research.labels import Direction


def load_catalogue_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "build_event_catalogue.py"
    spec = importlib.util.spec_from_file_location("build_event_catalogue", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module from {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


catalogue = load_catalogue_module()


def make_klines(high: list[float]) -> KlineArrays:
    n_rows = len(high)
    timestamps = np.arange(n_rows, dtype=np.int64) * 60 + 1_700_000_000
    ones = np.full(n_rows, 100.0)
    return KlineArrays(
        timestamp=timestamps,
        open=ones.copy(),
        high=np.asarray(high, dtype=np.float64),
        low=np.full(n_rows, 99.5),
        close=ones.copy(),
        volume=np.zeros(n_rows),
        n_rows=n_rows,
    )


class DecisionTimestampTests(unittest.TestCase):
    def test_decision_timestamp_is_interval_end(self) -> None:
        self.assertEqual(catalogue.decision_timestamp(1_700_000_000), 1_700_000_060)


class CollectPositiveAnchorsTests(unittest.TestCase):
    def test_anchors_are_stamped_at_bar_close(self) -> None:
        # Bars 0-2 see the +2% passage at bar 3 (high 103 from close 100).
        klines = make_klines([100.5, 100.5, 100.5, 103.0] + [100.5] * 6)
        labels = batch_first_passage(
            klines.high,
            klines.low,
            klines.close,
            horizon_bars=5,
            threshold_fraction=0.02,
        )
        anchors = catalogue.collect_positive_anchors(klines, labels, 0)
        self.assertEqual(len(anchors), 3)
        for offset, anchor in enumerate(anchors):
            self.assertEqual(anchor.direction, Direction.UP)
            self.assertEqual(
                anchor.anchor_timestamp,
                int(klines.timestamp[offset]) + catalogue.STEP_SECONDS,
            )
            self.assertEqual(
                anchor.passage_timestamp,
                int(klines.timestamp[3]) + catalogue.STEP_SECONDS,
            )

    def test_segment_start_offsets_absolute_indices(self) -> None:
        klines = make_klines([100.5, 100.5, 100.5, 103.0] + [100.5] * 6)
        labels = batch_first_passage(
            klines.high,
            klines.low,
            klines.close,
            horizon_bars=5,
            threshold_fraction=0.02,
            segment=(1, 10),
        )
        anchors = catalogue.collect_positive_anchors(klines, labels, 1)
        self.assertEqual(len(anchors), 2)
        self.assertEqual(
            anchors[0].anchor_timestamp,
            int(klines.timestamp[1]) + catalogue.STEP_SECONDS,
        )


class ClusterRecordTests(unittest.TestCase):
    def test_directional_record(self) -> None:
        cluster = EventCluster(
            start_timestamp=1_700_000_060,
            end_timestamp=1_700_000_360,
            anchor_count=3,
            up_count=3,
            down_count=0,
        )
        record = catalogue._cluster_record(cluster)
        self.assertEqual(record["direction"], "up")
        self.assertEqual(record["start"], "2023-11-14T22:14:20Z")
        self.assertEqual(record["start_timestamp"], 1_700_000_060)
        self.assertEqual(record["end_timestamp"], 1_700_000_360)
        self.assertEqual(record["anchor_count"], 3)

    def test_mixed_record(self) -> None:
        cluster = EventCluster(
            start_timestamp=1_700_000_060,
            end_timestamp=1_700_000_360,
            anchor_count=2,
            up_count=1,
            down_count=1,
        )
        self.assertEqual(catalogue._cluster_record(cluster)["direction"], "mixed")


class LabelHorizonRecordTests(unittest.TestCase):
    def test_records_match_summary_counts(self) -> None:
        klines = make_klines([100.5, 100.5, 100.5, 103.0] + [100.5] * 6)
        segments = [(0, klines.n_rows)]
        summary, records = catalogue._label_horizon(
            klines, segments, horizon_bars=5, threshold=0.02
        )
        self.assertEqual(summary["clusters"]["total"], len(records))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["direction"], "up")
        self.assertEqual(records[0]["anchor_count"], 3)
        self.assertEqual(
            records[0]["start_timestamp"],
            int(klines.timestamp[0]) + catalogue.STEP_SECONDS,
        )
        self.assertEqual(
            records[0]["end_timestamp"],
            int(klines.timestamp[3]) + catalogue.STEP_SECONDS,
        )


if __name__ == "__main__":
    unittest.main()
