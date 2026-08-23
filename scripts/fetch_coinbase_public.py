#!/usr/bin/env python3
"""Idempotent downloader for Coinbase Exchange public 1-minute candles.

Codifies the 2026-08-23 acquisition: tile BTC-USD history
2019-12-01T00:00:00Z .. 2026-08-01T00:00:00Z (end exclusive) into
non-overlapping 300-minute windows against

    GET https://api.exchange.coinbase.com/products/BTC-USD/candles

Empirical tiling (verified 2026-08-23): the API treats ``start`` and ``end``
inclusively. A request for ``T`` .. ``T+300min`` returns 301 buckets and
duplicates the next window's first minute. Request ``T`` .. ``T+299min`` to
get exactly the 300 interval-start stamps ``[T, T+299min]``. The next window
starts at ``T+300min``. Buckets with no trades are omitted (structural
absence). Empty JSON arrays are stored verbatim as evidence.
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

CANDLES_BASE = "https://api.exchange.coinbase.com/products"
DEFAULT_PRODUCT = "BTC-USD"
DEFAULT_GRANULARITY = 60
DEFAULT_WINDOW_MINUTES = 300
# Inclusive API: request this many minutes after start (300 buckets).
DEFAULT_REQUEST_SPAN_MINUTES = 299
DEFAULT_START = "2019-12-01T00:00:00Z"
DEFAULT_END = "2026-08-01T00:00:00Z"
DEFAULT_SLEEP_S = 0.3
DEFAULT_MAX_ATTEMPTS = 8
DEFAULT_MAX_CONSECUTIVE_FAILURES = 8
USER_AGENT = "oracle-coinbase-fetch/1.0"
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def parse_iso_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def iso_utc_from_unix(timestamp_s: int) -> str:
    return datetime.fromtimestamp(int(timestamp_s), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def window_starts(
    range_start: datetime,
    range_end: datetime,
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
) -> list[int]:
    """Return unix-second starts for adjacent non-overlapping windows.

    ``range_end`` is exclusive. Each start is ``window_minutes`` after the
    previous. The last window is included only when it begins before
    ``range_end``.
    """
    if window_minutes <= 0:
        raise ValueError("window_minutes must be positive")
    start_s = int(range_start.timestamp())
    end_s = int(range_end.timestamp())
    step = window_minutes * 60
    starts: list[int] = []
    current = start_s
    while current < end_s:
        starts.append(current)
        current += step
    return starts


def request_end_unix(
    window_start: int,
    *,
    range_end: int,
    request_span_minutes: int = DEFAULT_REQUEST_SPAN_MINUTES,
) -> int:
    """Inclusive request-end unix seconds for one tiled window.

    Default span is 299 minutes so an inclusive API returns 300 buckets
    and the next window's start (``window_start + 300min``) is not fetched.
    The end is clipped to the last minute that begins before ``range_end``.
    """
    if request_span_minutes < 0:
        raise ValueError("request_span_minutes must be non-negative")
    requested = window_start + request_span_minutes * 60
    last_allowed = range_end - 60
    return min(requested, last_allowed)


def candles_url(
    *,
    product: str,
    start: str,
    end: str,
    granularity: int = DEFAULT_GRANULARITY,
) -> str:
    query = urllib.parse.urlencode(
        {
            "granularity": granularity,
            "start": start,
            "end": end,
        }
    )
    return f"{CANDLES_BASE}/{product}/candles?{query}"


def window_path(data_root: Path, product: str, window_start: int) -> Path:
    return (
        data_root
        / "raw"
        / "coinbase"
        / "candles"
        / product
        / "1m"
        / f"candles_{window_start}.json"
    )


def should_skip_existing(path: Path) -> bool:
    """Resume: skip a window only when the verbatim response file already exists."""
    return path.exists()


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def log_line(handle, message: str) -> None:
    handle.write(f"{utc_now_iso()} {message}\n")
    handle.flush()


def fetch_window_body(
    url: str,
    *,
    timeout: float = 60.0,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    log=None,
) -> str:
    """GET once per attempt; backoff on 429/5xx and transient network errors."""
    delay = 1.0
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            last_error = exc
            retryable = exc.code in RETRYABLE_STATUS
            if log is not None:
                log_line(
                    log,
                    f"RETRY attempt={attempt}/{max_attempts} status={exc.code} "
                    f"delay={delay:.1f} retryable={retryable} url={url}",
                )
            if not retryable:
                raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if log is not None:
                log_line(
                    log,
                    f"RETRY attempt={attempt}/{max_attempts} error={exc!s} "
                    f"delay={delay:.1f} url={url}",
                )
        if attempt < max_attempts:
            time.sleep(delay)
            delay = min(delay * 2, 60.0)
    raise RuntimeError(f"failed to fetch {url}: {last_error}")


def write_verbatim(dest: Path, text: str) -> None:
    """Write exact response text. Existing dest is left untouched (raw immutability)."""
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    part.write_text(text, encoding="utf-8")
    part.replace(dest)


def count_candle_rows(text: str) -> int:
    stripped = text.strip()
    if stripped in {"", "[]"}:
        return 0
    # Response is a JSON array of 6-element buckets; count objects without
    # re-serializing. A leading '[' plus one '[' per row is not reliable, so
    # count the unix-time integers that start each bucket.
    return stripped.count("[") - 1 if stripped.startswith("[") else 0


def run_fetch(
    *,
    data_root: Path,
    product: str,
    range_start: datetime,
    range_end: datetime,
    sleep_s: float,
    log,
    dry_run: bool,
) -> dict[str, int]:
    range_end_s = int(range_end.timestamp())
    starts = window_starts(range_start, range_end)
    summary = {
        "windows": len(starts),
        "downloaded": 0,
        "skipped": 0,
        "empty": 0,
        "errors": 0,
        "retries": 0,
    }
    log_line(
        log,
        f"START windows={len(starts)} product={product} "
        f"start={iso_utc_from_unix(int(range_start.timestamp()))} "
        f"end={iso_utc_from_unix(range_end_s)} sleep_s={sleep_s}",
    )
    if dry_run:
        if starts:
            first_end = request_end_unix(starts[0], range_end=range_end_s)
            last_end = request_end_unix(starts[-1], range_end=range_end_s)
            log_line(
                log,
                "DRY_RUN first="
                + candles_url(
                    product=product,
                    start=iso_utc_from_unix(starts[0]),
                    end=iso_utc_from_unix(first_end),
                ),
            )
            log_line(
                log,
                "DRY_RUN last="
                + candles_url(
                    product=product,
                    start=iso_utc_from_unix(starts[-1]),
                    end=iso_utc_from_unix(last_end),
                ),
            )
        log_line(log, "DRY_RUN complete")
        return summary

    consecutive_failures = 0
    for index, window_start in enumerate(starts, start=1):
        dest = window_path(data_root, product, window_start)
        if should_skip_existing(dest):
            summary["skipped"] += 1
            consecutive_failures = 0
            if index == 1 or index == len(starts) or index % 50 == 0:
                log_line(
                    log,
                    f"window={index}/{len(starts)} start={window_start} status=skipped",
                )
            continue

        request_end = request_end_unix(window_start, range_end=range_end_s)
        url = candles_url(
            product=product,
            start=iso_utc_from_unix(window_start),
            end=iso_utc_from_unix(request_end),
        )
        try:
            body = fetch_window_body(url, log=log)
            write_verbatim(dest, body)
            rows = count_candle_rows(body)
            summary["downloaded"] += 1
            if rows == 0:
                summary["empty"] += 1
            consecutive_failures = 0
            status = "empty" if rows == 0 else "downloaded"
            if index == 1 or index == len(starts) or index % 50 == 0 or rows == 0:
                log_line(
                    log,
                    f"window={index}/{len(starts)} start={window_start} "
                    f"status={status} bars={rows}",
                )
        except (urllib.error.HTTPError, RuntimeError, OSError) as exc:
            summary["errors"] += 1
            consecutive_failures += 1
            log_line(
                log,
                f"FAIL window={index}/{len(starts)} start={window_start} "
                f"consecutive={consecutive_failures} error={exc!s}",
            )
            if consecutive_failures >= DEFAULT_MAX_CONSECUTIVE_FAILURES:
                log_line(
                    log,
                    f"ABORT after {consecutive_failures} consecutive hard failures",
                )
                raise RuntimeError(
                    f"aborted after {consecutive_failures} consecutive hard failures"
                ) from exc

        time.sleep(sleep_s)

    log_line(
        log,
        "DONE "
        + " ".join(f"{key}={value}" for key, value in summary.items()),
    )
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download Coinbase Exchange public BTC-USD 1-minute candles "
            "in idempotent 300-minute windows."
        ),
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        required=True,
        help="External immutable raw-data root.",
    )
    parser.add_argument("--product", default=DEFAULT_PRODUCT)
    parser.add_argument(
        "--start",
        default=DEFAULT_START,
        help="Inclusive UTC range start (default: 2019-12-01T00:00:00Z).",
    )
    parser.add_argument(
        "--end",
        default=DEFAULT_END,
        help="Exclusive UTC range end (default: 2026-08-01T00:00:00Z).",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=DEFAULT_SLEEP_S,
        dest="sleep_s",
        help="Seconds to sleep after each request (default: 0.3, <= 4 req/s).",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="Progress log path (default: stdout).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned window count and first/last URLs; no network writes.",
    )
    return parser.parse_args(argv)


def dry_run_summary(args: argparse.Namespace) -> None:
    range_start = parse_iso_utc(args.start)
    range_end = parse_iso_utc(args.end)
    starts = window_starts(range_start, range_end)
    range_end_s = int(range_end.timestamp())
    print(f"product: {args.product}")
    print(f"windows: {len(starts)}")
    print(f"start: {args.start}")
    print(f"end: {args.end}")
    if not starts:
        return
    first_end = request_end_unix(starts[0], range_end=range_end_s)
    last_end = request_end_unix(starts[-1], range_end=range_end_s)
    print(
        "first: "
        + candles_url(
            product=args.product,
            start=iso_utc_from_unix(starts[0]),
            end=iso_utc_from_unix(first_end),
        )
    )
    print(
        "last: "
        + candles_url(
            product=args.product,
            start=iso_utc_from_unix(starts[-1]),
            end=iso_utc_from_unix(last_end),
        )
    )
    span = timedelta(minutes=DEFAULT_WINDOW_MINUTES)
    print(
        f"tiling: request start..start+{DEFAULT_REQUEST_SPAN_MINUTES}min; "
        f"next window = start+{span}"
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.dry_run and args.log is None:
        dry_run_summary(args)
        return 0

    range_start = parse_iso_utc(args.start)
    range_end = parse_iso_utc(args.end)
    if range_end <= range_start:
        print("end must be after start", file=sys.stderr)
        return 2

    log_handle = sys.stdout
    close_log = False
    if args.log is not None:
        args.log.parent.mkdir(parents=True, exist_ok=True)
        log_handle = args.log.open("a", encoding="utf-8")
        close_log = True
    try:
        run_fetch(
            data_root=args.data_root,
            product=args.product,
            range_start=range_start,
            range_end=range_end,
            sleep_s=args.sleep_s,
            log=log_handle,
            dry_run=args.dry_run,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    finally:
        if close_log:
            log_handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
