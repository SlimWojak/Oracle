#!/usr/bin/env python3
"""Idempotent downloader for public Binance Vision monthly/daily dumps."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

BASE_URL = "https://data.binance.vision"

DatasetName = Literal["spot_klines_1m", "um_klines_1m", "um_funding", "um_metrics"]
FetchStatus = Literal[
    "downloaded",
    "verified_existing",
    "skipped_existing",
    "missing",
    "checksum_mismatch",
    "error",
]

ALL_DATASETS: tuple[DatasetName, ...] = (
    "spot_klines_1m",
    "um_klines_1m",
    "um_funding",
    "um_metrics",
)

DATASET_CONFIG: dict[DatasetName, dict[str, str]] = {
    "spot_klines_1m": {
        "kind": "monthly",
        "start": "2020-01",
        "end": "2026-07",
        "path": "data/spot/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-{period}.zip",
    },
    "um_klines_1m": {
        "kind": "monthly",
        "start": "2020-01",
        "end": "2026-07",
        "path": "data/futures/um/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-{period}.zip",
    },
    "um_funding": {
        "kind": "monthly",
        "start": "2020-01",
        "end": "2026-07",
        "path": (
            "data/futures/um/monthly/fundingRate/BTCUSDT/"
            "BTCUSDT-fundingRate-{period}.zip"
        ),
    },
    "um_metrics": {
        "kind": "daily",
        "start": "2021-12-01",
        "end": "2026-08-21",
        "path": "data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-{period}.zip",
    },
}


def month_range(start_ym: str, end_ym: str) -> list[str]:
    """Return inclusive YYYY-MM strings from start_ym through end_ym."""
    start_year, start_month = (int(part) for part in start_ym.split("-"))
    end_year, end_month = (int(part) for part in end_ym.split("-"))
    months: list[str] = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            month = 1
            year += 1
    return months


def day_range(start_date: str, end_date: str) -> list[str]:
    """Return inclusive YYYY-MM-DD strings from start_date through end_date."""
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if start > end:
        return []
    days: list[str] = []
    current = start
    while current <= end:
        days.append(current.isoformat())
        current = date.fromordinal(current.toordinal() + 1)
    return days


def dataset_urls(name: DatasetName) -> list[str]:
    """Return full download URLs for a supported dataset."""
    config = DATASET_CONFIG[name]
    if config["kind"] == "monthly":
        periods = month_range(config["start"], config["end"])
    else:
        periods = day_range(config["start"], config["end"])
    return [f"{BASE_URL}/{config['path'].format(period=period)}" for period in periods]


def parse_checksum_line(text: str) -> str:
    """Parse a Binance Vision .CHECKSUM line and return the sha256 hex digest."""
    line = text.strip()
    if not line:
        raise ValueError("empty checksum line")
    parts = line.split()
    if len(parts) < 2:
        raise ValueError(f"malformed checksum line: {text!r}")
    digest = parts[0].lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError(f"invalid sha256 digest in checksum line: {text!r}")
    return digest


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Return the sha256 hex digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def relative_path_from_url(url: str) -> str:
    """Map a Binance Vision URL to the storage path under raw/binance_vision/."""
    prefix = f"{BASE_URL}/data/"
    if not url.startswith(prefix):
        raise ValueError(f"unexpected Binance Vision URL: {url}")
    return url[len(prefix) :]


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def http_get(url: str, timeout: float = 120.0) -> tuple[int, bytes | None]:
    """GET a URL once, retrying once after 5s on non-404 network errors."""
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "oracle-binance-fetch/1.0"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return 404, None
            last_error = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
        if attempt == 0:
            time.sleep(5)
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"failed to fetch {url}")


def fetch_checksum_digest(checksum_url: str) -> tuple[str | None, FetchStatus | None]:
    """Fetch and parse a .CHECKSUM file, returning (digest, blocking_status)."""
    try:
        status_code, body = http_get(checksum_url)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None, "error"
    if status_code == 404:
        return None, "missing"
    if body is None:
        return None, "error"
    try:
        return parse_checksum_line(body.decode("utf-8")), None
    except ValueError:
        return None, "error"


def make_manifest_record(
    *,
    url: str,
    relative_path: str,
    status: FetchStatus,
    sha256: str | None = None,
    size_bytes: int | None = None,
) -> dict[str, object]:
    return {
        "url": url,
        "relative_path": relative_path,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "status": status,
        "retrieved_at": utc_now_iso(),
    }


class ManifestWriter:
    def __init__(self, manifest_path: Path) -> None:
        self.manifest_path = manifest_path
        self._lock = threading.Lock()
        self._verified_paths = self._load_verified_paths()

    def _load_verified_paths(self) -> set[str]:
        if not self.manifest_path.exists():
            return set()
        verified: set[str] = set()
        with self.manifest_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if record.get("status") in {"downloaded", "verified_existing"}:
                    relative_path = record.get("relative_path")
                    if isinstance(relative_path, str):
                        verified.add(relative_path)
        return verified

    def append(self, record: dict[str, object]) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")

    def already_verified(self, relative_path: str) -> bool:
        with self._lock:
            return relative_path in self._verified_paths

    def mark_verified(self, relative_path: str) -> None:
        with self._lock:
            self._verified_paths.add(relative_path)


class DatasetSummary:
    def __init__(self) -> None:
        self.downloaded = 0
        self.existing = 0
        self.missing = 0
        self.errors = 0

    def record(self, status: FetchStatus) -> None:
        if status == "downloaded":
            self.downloaded += 1
        elif status in {"verified_existing", "skipped_existing"}:
            self.existing += 1
        elif status == "missing":
            self.missing += 1
        else:
            self.errors += 1


def process_url(
    url: str,
    *,
    data_root: Path,
    manifest: ManifestWriter,
    dry_run: bool,
) -> FetchStatus:
    relative_path = relative_path_from_url(url)
    target_path = data_root / "raw" / "binance_vision" / relative_path
    checksum_url = f"{url}.CHECKSUM"

    if dry_run:
        return "skipped_existing"

    expected_digest, checksum_status = fetch_checksum_digest(checksum_url)
    if checksum_status == "missing":
        manifest.append(
            make_manifest_record(
                url=url,
                relative_path=relative_path,
                status="missing",
            )
        )
        return "missing"
    if checksum_status == "error" or expected_digest is None:
        manifest.append(
            make_manifest_record(
                url=url,
                relative_path=relative_path,
                status="error",
            )
        )
        return "error"

    if target_path.exists():
        actual_digest = sha256_file(target_path)
        if actual_digest == expected_digest:
            if manifest.already_verified(relative_path):
                return "skipped_existing"
            manifest.append(
                make_manifest_record(
                    url=url,
                    relative_path=relative_path,
                    status="verified_existing",
                    sha256=actual_digest,
                    size_bytes=target_path.stat().st_size,
                )
            )
            manifest.mark_verified(relative_path)
            return "verified_existing"

    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_suffix(target_path.suffix + ".part")

    try:
        status_code, body = http_get(url)
        if status_code == 404:
            manifest.append(
                make_manifest_record(
                    url=url,
                    relative_path=relative_path,
                    status="missing",
                )
            )
            return "missing"
        if body is None:
            raise RuntimeError(f"empty response body for {url}")

        temp_path.write_bytes(body)
        actual_digest = sha256_file(temp_path)
        size_bytes = temp_path.stat().st_size
        if actual_digest != expected_digest:
            temp_path.unlink(missing_ok=True)
            manifest.append(
                make_manifest_record(
                    url=url,
                    relative_path=relative_path,
                    status="checksum_mismatch",
                    sha256=actual_digest,
                    size_bytes=size_bytes,
                )
            )
            return "checksum_mismatch"

        temp_path.replace(target_path)

        manifest.append(
            make_manifest_record(
                url=url,
                relative_path=relative_path,
                status="downloaded",
                sha256=actual_digest,
                size_bytes=target_path.stat().st_size,
            )
        )
        manifest.mark_verified(relative_path)
        return "downloaded"
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        temp_path.unlink(missing_ok=True)
        manifest.append(
            make_manifest_record(
                url=url,
                relative_path=relative_path,
                status="error",
            )
        )
        return "error"


def dry_run_summary(datasets: list[DatasetName]) -> None:
    for name in datasets:
        count = len(dataset_urls(name))
        print(f"{name}: {count} files")


def run_fetch(
    *,
    data_root: Path,
    datasets: list[DatasetName],
    workers: int,
    dry_run: bool,
) -> dict[DatasetName, DatasetSummary]:
    summaries: dict[DatasetName, DatasetSummary] = {name: DatasetSummary() for name in datasets}

    if dry_run:
        dry_run_summary(datasets)
        return summaries

    manifest = ManifestWriter(data_root / "manifests" / "binance_vision_fetch.jsonl")

    for name in datasets:
        urls = dataset_urls(name)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    process_url,
                    url,
                    data_root=data_root,
                    manifest=manifest,
                    dry_run=False,
                ): url
                for url in urls
            }
            for future in as_completed(futures):
                status = future.result()
                summaries[name].record(status)

    return summaries


def print_summary(summaries: dict[DatasetName, DatasetSummary], *, dry_run: bool) -> None:
    if dry_run:
        return
    print("Summary:")
    for name, summary in summaries.items():
        print(
            f"{name}: downloaded={summary.downloaded} existing={summary.existing} "
            f"missing={summary.missing} errors={summary.errors}"
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download public Binance Vision dumps with checksum verification.",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        required=True,
        help="External immutable raw-data root.",
    )
    parser.add_argument(
        "--datasets",
        default=",".join(ALL_DATASETS),
        help="Comma-separated dataset names (default: all).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of concurrent download workers.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print file counts per dataset and exit without network writes.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    requested = [part.strip() for part in args.datasets.split(",") if part.strip()]
    unknown = [name for name in requested if name not in DATASET_CONFIG]
    if unknown:
        print(f"Unknown datasets: {', '.join(unknown)}", file=sys.stderr)
        return 2

    datasets = [name for name in requested if name in DATASET_CONFIG]
    summaries = run_fetch(
        data_root=args.data_root,
        datasets=datasets,
        workers=args.workers,
        dry_run=args.dry_run,
    )
    print_summary(summaries, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
