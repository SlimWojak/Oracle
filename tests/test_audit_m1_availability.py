from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path


def load_audit_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "audit_m1_availability.py"
    spec = importlib.util.spec_from_file_location("audit_m1_availability", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module from {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


audit = load_audit_module()

KLINE_HEADER = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trade_count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "ignore",
]


def epoch_seconds(value: datetime) -> int:
    return int(value.timestamp())


def kline_row(
    interval_end: datetime,
    *,
    unit: str,
    close: float = 100.0,
    quote_volume: float = 100.0,
    taker_buy_quote: float = 45.0,
) -> list[object]:
    start_seconds = epoch_seconds(interval_end) - 60
    end_seconds = epoch_seconds(interval_end)
    if unit == "ms":
        open_time = start_seconds * 1_000
        close_time = end_seconds * 1_000 - 1
    elif unit == "us":
        open_time = start_seconds * 1_000_000
        close_time = end_seconds * 1_000_000 - 1
    else:
        raise ValueError(unit)
    return [
        open_time,
        close,
        close,
        close,
        close,
        1.0,
        close_time,
        quote_volume,
        1,
        taker_buy_quote / close,
        taker_buy_quote,
        0,
    ]


def write_zip(
    data_root: Path,
    relative_path: str,
    rows: list[list[object]],
    *,
    header: list[str] | None,
) -> Path:
    path = data_root / "raw" / "binance_vision" / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    if header is not None:
        writer.writerow(header)
    writer.writerows(rows)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{path.stem}.csv", buffer.getvalue())
    return path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_fixture(
    data_root: Path,
    *,
    conflicting_metrics: bool = False,
    invalid_spot_close_time: bool = False,
) -> tuple[tuple[object, ...], tuple[object, ...]]:
    decision = datetime(2024, 1, 1, 12, tzinfo=UTC)
    paths = {
        "spot_klines_1m": "spot/monthly/klines/BTCUSDT/1m/spot.zip",
        "um_klines_1m": "futures/um/monthly/klines/BTCUSDT/1m/perp.zip",
        "funding": "futures/um/monthly/fundingRate/BTCUSDT/funding.zip",
        "metrics": "futures/um/daily/metrics/BTCUSDT/metrics.zip",
    }

    # Headerless milliseconds and an exact one-minute hole exercise both legacy
    # positional parsing and gap accounting while retaining the bar ending at T.
    spot_rows = [
        kline_row(decision - timedelta(minutes=2), unit="ms"),
        kline_row(decision, unit="ms"),
    ]
    # A one-millisecond-early close is causal but nonstandard and must remain
    # observable in the audit. The alternate fixture exceeds nominal end.
    spot_rows[-1][6] = int(spot_rows[-1][6]) - 1
    if invalid_spot_close_time:
        spot_rows[-1][6] = epoch_seconds(decision) * 1_000 + 1
    written: dict[str, Path] = {
        "spot_klines_1m": write_zip(
            data_root,
            paths["spot_klines_1m"],
            spot_rows,
            header=None,
        )
    }

    # The exact flow rule at T needs minute bars ending 02:01..11:55, then the
    # premium pair needs the bar ending at 12:00. Alternating block ratios leave
    # a positive residual variance without loading a large fixture.
    first_end = decision.replace(hour=2, minute=1)
    perp_rows: list[list[object]] = []
    current = first_end
    while current <= decision:
        block = epoch_seconds(current) // 300
        buy_quote = 35.0 + float((block * block + 3 * block) % 21)
        perp_rows.append(
            kline_row(
                current,
                unit="us",
                close=101.0,
                quote_volume=100.0,
                taker_buy_quote=buy_quote,
            )
        )
        current += timedelta(minutes=1)
    written["um_klines_1m"] = write_zip(
        data_root,
        paths["um_klines_1m"],
        perp_rows,
        header=KLINE_HEADER,
    )

    metric_time_ms = (epoch_seconds(decision) - 300) * 1_000
    metric_rows = [[metric_time_ms, "BTCUSDT", 50_000.0]]
    if conflicting_metrics:
        metric_rows.append([metric_time_ms, "BTCUSDT", 50_001.0])
    written["metrics"] = write_zip(
        data_root,
        paths["metrics"],
        metric_rows,
        header=["create_time", "symbol", "sum_open_interest_value"],
    )

    # Jitter remains in the raw millisecond event stamps. It is not rounded to
    # an eight-hour grid, yet all three settlements are in the frozen window.
    funding_rows: list[list[object]] = []
    for settlement, jitter, rate in (
        (decision - timedelta(hours=24), 123, 0.0001),
        (decision - timedelta(hours=16), 456, -0.0002),
        (decision - timedelta(hours=8), 789, 0.0003),
    ):
        funding_rows.append([epoch_seconds(settlement) * 1_000 + jitter, 8, rate])
    written["funding"] = write_zip(
        data_root,
        paths["funding"],
        funding_rows,
        header=["calc_time", "funding_interval_hours", "last_funding_rate"],
    )

    manifest_path = data_root / audit.MANIFEST_IDENTIFIER
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    records = []
    for source, relative_path in paths.items():
        path = written[source]
        records.append(
            {
                "url": f"https://data.binance.vision/data/{relative_path}",
                "relative_path": relative_path,
                "sha256": sha256(path),
                "size_bytes": path.stat().st_size,
                "status": "downloaded",
                "retrieved_at": "2026-08-25T00:00:00+00:00",
            }
        )
    manifest_path.write_text(
        "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records),
        encoding="utf-8",
    )
    identities = tuple(
        audit.ArchiveIdentity(source, relative_path)
        for source, relative_path in paths.items()
    )
    periods = (
        audit.AuditPeriod("SYNTHETIC", decision, decision),
    )
    return identities, periods


class ExactTimestampTests(unittest.TestCase):
    def test_epoch_ms_and_us_are_normalized_without_fractional_flooring(self) -> None:
        milliseconds, ms_unit = audit.parse_epoch_us_exact(
            "1704067200000", field_name="open_time"
        )
        microseconds, us_unit = audit.parse_epoch_us_exact(
            "1704067200000000", field_name="open_time"
        )
        self.assertEqual(milliseconds, 1_704_067_200_000_000)
        self.assertEqual(microseconds, milliseconds)
        self.assertEqual(ms_unit, "epoch_ms")
        self.assertEqual(us_unit, "epoch_us")
        with self.assertRaises(ValueError):
            audit.parse_funding_calc_time_ms_exact("1704067200123.5")

    def test_expected_production_identity_counts_are_exact(self) -> None:
        counts: dict[str, int] = {}
        identities = audit.expected_archive_identities()
        for identity in identities:
            counts[identity.source] = counts.get(identity.source, 0) + 1
        self.assertEqual(
            counts,
            {
                "spot_klines_1m": 79,
                "um_klines_1m": 79,
                "funding": 79,
                "metrics": 1725,
            },
        )
        self.assertEqual(len(identities), 1962)


class AvailabilityAuditTests(unittest.TestCase):
    def test_full_synthetic_coverage_passes_but_m1_remains_asof_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            identities, periods = make_fixture(root)
            payload, _ = audit.build_audit_payload(
                data_root=root,
                identities=identities,
                periods=periods,
            )

        self.assertTrue(payload["manifest"]["exact_identity_set"])
        self.assertTrue(payload["availability"]["coverage_clearance"])
        self.assertEqual(payload["overall_m1_status"], "BLOCKED_ASOF")
        self.assertEqual(
            payload["publication_evidence"],
            {
                "funding": "BLOCKED_ASOF_NO_PUBLICATION_TIME",
                "open_interest": "BLOCKED_ASOF_NO_PUBLICATION_TIME",
                "perpetual_premium": "CLEARED_INTERVAL_END",
                "taker_flow_variance_compression": "CLEARED_INTERVAL_END",
            },
        )
        availability = payload["availability"]["periods"]["SYNTHETIC"]
        for family in availability["families"].values():
            self.assertEqual(family["available_hours"], 1)
            self.assertTrue(family["floor_pass"])
        self.assertEqual(availability["joint"]["available_hours"], 1)

        spot = payload["sources"]["spot_klines_1m"]
        perp = payload["sources"]["um_klines_1m"]
        self.assertEqual(spot["headerless_archives"], 1)
        self.assertEqual(spot["timestamp_units"], {"epoch_ms": 2})
        self.assertEqual(perp["timestamp_units"], {"epoch_us": 600})
        self.assertEqual(spot["raw_timestamp_gaps"]["gap_count"], 1)
        self.assertEqual(spot["raw_timestamp_gaps"]["missing_intervals"], 1)
        self.assertEqual(spot["close_time_audit"]["after_interval_end"], 0)
        self.assertEqual(spot["close_time_audit"]["nonstandard_offset"], 1)

        funding = payload["sources"]["funding"]
        self.assertEqual(funding["off_grid_rows"], 3)
        self.assertEqual(funding["raw_settlement_delta_ms"]["minimum"], 28_800_333)
        self.assertFalse(
            funding["raw_settlement_delta_ms"]["nominal_grid_rounding_applied"]
        )

    def test_conflicting_metric_timestamp_is_unusable_and_fails_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            identities, periods = make_fixture(root, conflicting_metrics=True)
            payload, _ = audit.build_audit_payload(
                data_root=root,
                identities=identities,
                periods=periods,
            )

        metrics = payload["sources"]["metrics"]
        self.assertEqual(metrics["duplicates"]["duplicate_rows"], 1)
        self.assertEqual(metrics["duplicates"]["conflicting_timestamps"], 1)
        period = payload["availability"]["periods"]["SYNTHETIC"]
        self.assertEqual(period["families"]["open_interest"]["available_hours"], 0)
        self.assertFalse(payload["availability"]["coverage_clearance"])
        self.assertEqual(payload["overall_m1_status"], "BLOCKED_ASOF")

    def test_bar_published_after_nominal_end_is_audited_and_unusable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            identities, periods = make_fixture(root, invalid_spot_close_time=True)
            payload, _ = audit.build_audit_payload(
                data_root=root,
                identities=identities,
                periods=periods,
            )

        spot = payload["sources"]["spot_klines_1m"]
        self.assertEqual(spot["close_time_audit"]["after_interval_end"], 1)
        period = payload["availability"]["periods"]["SYNTHETIC"]
        self.assertEqual(period["families"]["perpetual_premium"]["available_hours"], 0)
        self.assertFalse(payload["availability"]["coverage_clearance"])

    def test_zero_joint_full_month_is_reported(self) -> None:
        start = datetime(2024, 2, 1, tzinfo=UTC)
        end = datetime(2024, 2, 29, 23, tzinfo=UTC)
        period = audit.AuditPeriod("FEB", start, end)
        report = audit._availability_report(  # noqa: SLF001 - pure audit primitive
            periods=(period,),
            families={
                "funding": set(),
                "open_interest": set(),
                "perpetual_premium": set(),
                "taker_flow_variance_compression": set(),
            },
        )
        self.assertEqual(report["zero_joint_full_months"], ["2024-02"])
        self.assertFalse(report["coverage_clearance"])

    def test_writer_provenance_uses_relative_manifest_identifier_and_hashes_outputs(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "data"
            output = Path(tmp) / "reports"
            root.mkdir()
            identities, periods = make_fixture(root)
            json_path, md_path, provenance_path = audit.write_audit(
                data_root=root,
                output_dir=output,
                repo_root=repo_root,
                identities=identities,
                periods=periods,
            )
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))

        self.assertEqual(provenance["input_manifest_identifier"], audit.MANIFEST_IDENTIFIER)
        self.assertEqual(len(provenance["input_manifest_sha256"]), 64)
        self.assertEqual({item["path"] for item in provenance["outputs"]}, {
            json_path.name,
            md_path.name,
        })
        self.assertNotIn(str(root), json.dumps(provenance))


if __name__ == "__main__":
    unittest.main()
