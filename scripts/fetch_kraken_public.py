#!/usr/bin/env python3
"""Idempotent Kraken public OHLCVT extract + optional raw Trades tail.

Codifies the 2026-08-23 acquisition: official Drive complete ZIP (possibly
supplied locally after a browser download), extract ``master_q4/XBTUSD_1.csv``,
and page the public Trades endpoint without aggregating bars.
"""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SUPPORT_ARTICLE_URL = (
    "https://support.kraken.com/articles/"
    "360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data"
)
TRADES_ENDPOINT = "https://api.kraken.com/0/public/Trades"
DRIVE_UC_BASE = "https://drive.google.com/uc"

# Official Drive IDs linked from SUPPORT_ARTICLE_URL as of 2026-08-23.
COMPLETE_DRIVE_FILE_ID = "1ptNqWYidLkhb2VAKuLCxmp2OXEfGO-AP"
QUARTERLY_DRIVE_FOLDER_ID = "15RSlNuW_h0kVM8or8McOGOMfHeBFvFGI"
DEFAULT_ZIP_NAME = "Kraken_OHLCVT.zip"
DEFAULT_ZIP_MEMBER = "master_q4/XBTUSD_1.csv"
DEFAULT_EXTRACTED_CSV = "XBTUSD_1.csv"
DEFAULT_Q1_ZIP_NAME = "Kraken_OHLCVT_Q1_2026.zip"
DEFAULT_Q1_ZIP_MEMBER = "XBTUSD_1.csv"
DEFAULT_Q1_EXTRACTED_CSV = "XBTUSD_1_Q1_2026.csv"

USER_AGENT = "oracle-kraken-fetch/1.0"
CHUNK_SIZE = 1024 * 1024
DRIVE_FILE_ID_RE = re.compile(r"drive\.google\.com/file/d/([A-Za-z0-9_-]+)")
DRIVE_FOLDER_ID_RE = re.compile(r"drive\.google\.com/drive/folders/([A-Za-z0-9_-]+)")
FOLDER_ZIP_RE = re.compile(
    r"(1[A-Za-z0-9_-]{20,})-0-16.{0,800}?Kraken_OHLCVT_(Q[1-4]_\d{4})\.zip",
    re.DOTALL,
)
HIDDEN_INPUT_RE = re.compile(r"<input[^>]+>", re.IGNORECASE)
INPUT_NAME_RE = re.compile(r'name="([^"]+)"', re.IGNORECASE)
INPUT_VALUE_RE = re.compile(r'value="([^"]*)"', re.IGNORECASE)
FORM_ACTION_RE = re.compile(r'<form[^>]+action="([^"]+)"', re.IGNORECASE)


class DriveQuotaError(RuntimeError):
    """Google Drive virus-scan / anonymous-download quota is exhausted."""


def unix_seconds_to_ns(timestamp_s: int | float) -> int:
    """Convert a unix-seconds value to Kraken Trades `since` nanoseconds."""
    return int(float(timestamp_s) * 1_000_000_000)


def iso_utc_from_unix(timestamp_s: int | float) -> str:
    return datetime.fromtimestamp(int(timestamp_s), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def drive_file_view_url(file_id: str) -> str:
    return f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"


def drive_folder_url(folder_id: str) -> str:
    return f"https://drive.google.com/drive/folders/{folder_id}?usp=sharing"


def drive_uc_url(file_id: str, *, confirm: str | None = None) -> str:
    params = {"export": "download", "id": file_id}
    if confirm is not None:
        params["confirm"] = confirm
    return f"{DRIVE_UC_BASE}?{urllib.parse.urlencode(params)}"


def parse_support_article_drive_links(html: str) -> dict[str, str]:
    """Extract complete-file and quarterly-folder IDs from the official article HTML."""
    file_ids = DRIVE_FILE_ID_RE.findall(html)
    folder_ids = DRIVE_FOLDER_ID_RE.findall(html)
    if not file_ids or not folder_ids:
        raise ValueError("support article HTML is missing Google Drive links")
    return {
        "complete_file_id": file_ids[0],
        "quarterly_folder_id": folder_ids[0],
    }


def parse_drive_folder_zip_entries(html: str) -> list[tuple[str, str]]:
    """Return (filename, file_id) pairs for Kraken_OHLCVT_Qn_YYYY.zip entries."""
    seen: dict[str, str] = {}
    for file_id, quarter in FOLDER_ZIP_RE.findall(html):
        name = f"Kraken_OHLCVT_{quarter}.zip"
        seen.setdefault(name, file_id)
    return sorted(seen.items())


def parse_drive_confirm_form(html: str) -> dict[str, str]:
    """Parse the Google Drive virus-scan confirm form into action + hidden fields."""
    action = "https://drive.usercontent.google.com/download"
    match = FORM_ACTION_RE.search(html)
    if match:
        action = match.group(1)
    params: dict[str, str] = {"action": action}
    for tag in HIDDEN_INPUT_RE.findall(html):
        if "hidden" not in tag.lower():
            continue
        name_match = INPUT_NAME_RE.search(tag)
        value_match = INPUT_VALUE_RE.search(tag)
        if name_match:
            params[name_match.group(1)] = value_match.group(1) if value_match else ""
    return params


def confirm_form_download_url(form: dict[str, str]) -> str:
    params = dict(form)
    action = params.pop("action", "https://drive.usercontent.google.com/download")
    return f"{action}?{urllib.parse.urlencode(params)}"


def trades_request_url(pair: str, since_ns: int, count: int = 1000) -> str:
    query = urllib.parse.urlencode({"pair": pair, "since": since_ns, "count": count})
    return f"{TRADES_ENDPOINT}?{query}"


def parse_trades_page(payload: dict[str, Any]) -> dict[str, Any]:
    """Parse a raw Kraken Trades JSON object without aggregating bars."""
    errors = payload.get("error") or []
    if not isinstance(errors, list):
        errors = [errors]
    result = payload.get("result") or {}
    if not isinstance(result, dict):
        raise ValueError("trades payload missing result object")
    last = result.get("last")
    pair_key = next((key for key in result if key != "last"), None)
    trades = result.get(pair_key) if pair_key else []
    if trades is None:
        trades = []
    if not isinstance(trades, list):
        raise ValueError("trades payload has a non-list trade array")
    return {
        "errors": [str(item) for item in errors],
        "pair_key": pair_key,
        "trades": trades,
        "last": None if last is None else str(last),
        "trade_count": len(trades),
    }


def next_trades_since(last: str | None, prev_since: str | int) -> int | None:
    """Return the next `since` cursor, or None when pagination is exhausted/stuck."""
    if last is None:
        return None
    last_ns = int(last)
    prev_ns = int(prev_since)
    if last_ns <= prev_ns:
        return None
    return last_ns


def sha256_file(path: Path, chunk_size: int = CHUNK_SIZE) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def pair_csv_name(pair: str, interval: int) -> str:
    return f"{pair}_{interval}.csv"


def quarterly_csv_name(pair: str, interval: int, quarter: str) -> str:
    """Distinct extracted name so a quarterly CSV never clobbers the master."""
    return f"{pair}_{interval}_{quarter}.csv"


def find_zip_member(names: list[str], filename: str) -> str | None:
    """Pick a zip member, preferring an exact path then ``master_q4/`` then any suffix."""
    if filename in names:
        return filename
    preferred = f"master_q4/{filename}"
    if preferred in names:
        return preferred
    matches = [
        name
        for name in names
        if name.endswith(f"/{filename}") and not name.startswith("__MACOSX/")
    ]
    if not matches:
        return None
    master = [name for name in matches if name.startswith("master_q4/")]
    return sorted(master or matches)[-1]


def theoretical_minutes(year: int, *, window_end_year: int = 2026) -> int:
    """Calendar minutes in `year`, clipped to Jul 31 for 2026."""
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days = 366 if leap else 365
    if year == window_end_year:
        days = 31 + 28 + 31 + 30 + 31 + 30 + 31  # Jan–Jul, 2026 is not leap
    return days * 1440


def parse_iso_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def ohlcvt_dir(data_root: Path) -> Path:
    return data_root / "raw" / "kraken" / "ohlcvt"


def trades_dir(data_root: Path, pair: str) -> Path:
    return data_root / "raw" / "kraken" / "trades" / pair


def _is_html_body(content_type: str, first_chunk: bytes) -> bool:
    if "text/html" in content_type.lower():
        return True
    stripped = first_chunk.lstrip()
    return stripped.startswith((b"<!DOCTYPE", b"<html", b"<HTML"))


def _html_is_quota(html: str) -> bool:
    lowered = html.lower()
    return "quota exceeded" in lowered or "too many users have viewed or downloaded" in lowered


def download_google_drive_file(file_id: str, dest: Path) -> int:
    """Stream a public Drive file, handling the virus-scan confirm page."""
    if dest.exists():
        return dest.stat().st_size

    cookiejar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookiejar))
    first_url = drive_uc_url(file_id)
    request = urllib.request.Request(first_url, headers={"User-Agent": USER_AGENT})
    download_url = first_url

    with opener.open(request, timeout=120) as response:
        content_type = response.headers.get("Content-Type", "")
        first = response.read(8192)
        if _is_html_body(content_type, first):
            html = (first + response.read()).decode("utf-8", "replace")
            if _html_is_quota(html):
                raise DriveQuotaError(f"Google Drive quota exhausted for file id {file_id}")
            form = parse_drive_confirm_form(html)
            form.setdefault("id", file_id)
            form.setdefault("export", "download")
            form.setdefault("confirm", "t")
            download_url = confirm_form_download_url(form)
        else:
            return _stream_known_zip(response, dest, prefix=first)

    request = urllib.request.Request(download_url, headers={"User-Agent": USER_AGENT})
    with opener.open(request, timeout=120) as response:
        content_type = response.headers.get("Content-Type", "")
        first = response.read(16)
        if _is_html_body(content_type, first):
            html = (first + response.read()).decode("utf-8", "replace")
            if _html_is_quota(html):
                raise DriveQuotaError(f"Google Drive quota exhausted for file id {file_id}")
            raise RuntimeError(f"Drive download returned HTML for file id {file_id}")
        return _stream_known_zip(response, dest, prefix=first)


def _stream_known_zip(response: Any, dest: Path, *, prefix: bytes) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    written = len(prefix)
    with part.open("wb") as handle:
        handle.write(prefix)
        while True:
            chunk = response.read(CHUNK_SIZE)
            if not chunk:
                break
            handle.write(chunk)
            written += len(chunk)
    with part.open("rb") as handle:
        magic = handle.read(4)
    if magic != b"PK\x03\x04":
        part.unlink(missing_ok=True)
        raise RuntimeError(f"downloaded payload is not a zip (magic={magic!r})")
    part.replace(dest)
    return written


def extract_zip_member(zip_path: Path, member: str, dest: Path) -> Path:
    """Extract one zip member to dest. Existing dest is left untouched."""
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        resolved = member if member in names else find_zip_member(names, Path(member).name)
        if resolved is None:
            raise FileNotFoundError(f"{member} not found in {zip_path.name}")
        part = dest.with_suffix(dest.suffix + ".part")
        with archive.open(resolved) as source, part.open("wb") as handle:
            while True:
                chunk = source.read(CHUNK_SIZE)
                if not chunk:
                    break
                handle.write(chunk)
        part.replace(dest)
    return dest


def fetch_trades_page(pair: str, since_ns: int, count: int = 1000) -> dict[str, Any]:
    url = trades_request_url(pair, since_ns, count=count)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    delay = 2.0
    last_error: Exception | None = None
    for _attempt in range(8):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
            parsed = parse_trades_page(payload)
            errors = parsed["errors"]
            if errors:
                joined = " ".join(errors)
                if "Rate limit" in joined or "Too many requests" in joined:
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
                raise RuntimeError(joined)
            return payload
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504}:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 60)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            time.sleep(delay)
            delay = min(delay * 2, 60)
    raise RuntimeError(f"failed to fetch trades since={since_ns}: {last_error}")


def write_raw_json(dest: Path, payload: dict[str, Any]) -> None:
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    part.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    part.replace(dest)


def fetch_trades_tail(
    *,
    out_dir: Path,
    pair: str,
    since_ns: int,
    end_ns: int,
    sleep_s: float = 1.0,
    prefix: str = "page",
) -> dict[str, int]:
    """Fetch raw Trades pages from since_ns through end_ns. Does not build bars."""
    existing = sorted(out_dir.glob(f"{prefix}_*.json"))
    seq = 0
    if existing:
        last_payload = json.loads(existing[-1].read_text(encoding="utf-8"))
        parsed = parse_trades_page(last_payload)
        if parsed["last"] is not None:
            since_ns = max(since_ns, int(parsed["last"]))
        seq = int(existing[-1].stem.rsplit("_", 1)[-1])

    pages = 0
    while since_ns < end_ns:
        payload = fetch_trades_page(pair, since_ns)
        parsed = parse_trades_page(payload)
        nxt = next_trades_since(parsed["last"], since_ns)
        seq += 1
        write_raw_json(out_dir / f"{prefix}_{seq:06d}.json", payload)
        pages += 1
        if nxt is None:
            break
        since_ns = nxt
        time.sleep(sleep_s)
    return {"pages": pages, "last_seq": seq, "since_ns": since_ns}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract Kraken official OHLCVT XBTUSD 1m CSV from the complete ZIP "
            "and optionally page raw public Trades. Does not aggregate bars."
        ),
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        required=True,
        help="External immutable raw-data root.",
    )
    parser.add_argument("--pair", default="XBTUSD", help="Kraken pair code (default: XBTUSD).")
    parser.add_argument("--interval", type=int, default=1, help="OHLCVT interval minutes.")
    parser.add_argument(
        "--zip-name",
        default=DEFAULT_ZIP_NAME,
        help="Complete-archive filename under raw/kraken/ohlcvt/.",
    )
    parser.add_argument(
        "--zip-member",
        default=DEFAULT_ZIP_MEMBER,
        help="Member path inside the ZIP (default: master_q4/XBTUSD_1.csv).",
    )
    parser.add_argument(
        "--q1-zip-name",
        default=DEFAULT_Q1_ZIP_NAME,
        help="Q1 2026 quarterly archive filename under raw/kraken/ohlcvt/.",
    )
    parser.add_argument(
        "--q1-zip-member",
        default=DEFAULT_Q1_ZIP_MEMBER,
        help="Member path inside the Q1 ZIP (default: XBTUSD_1.csv at archive root).",
    )
    parser.add_argument(
        "--skip-ohlcvt",
        action="store_true",
        help="Skip ZIP download/extract.",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Do not hit Drive; only extract if the ZIP is already present.",
    )
    parser.add_argument(
        "--expected-sha256",
        default=None,
        help="If set, verify the existing ZIP digest before extract.",
    )
    parser.add_argument(
        "--tail-trades",
        action="store_true",
        help="Fetch raw Trades pages after --tail-since through --tail-end.",
    )
    parser.add_argument(
        "--tail-since",
        default="2026-01-01T00:00:00+00:00",
        help="UTC start for the trades tail (default: after Q4 2025 export).",
    )
    parser.add_argument(
        "--tail-end",
        default="2026-08-01T00:00:00+00:00",
        help="Exclusive UTC end for the trades tail.",
    )
    parser.add_argument(
        "--page-prefix",
        default="page",
        help="Filename prefix for raw trade pages (default: page).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned sources and exit without network writes.",
    )
    return parser.parse_args(argv)


def dry_run_summary(args: argparse.Namespace) -> None:
    print(f"support_article: {SUPPORT_ARTICLE_URL}")
    print(f"complete: {drive_file_view_url(COMPLETE_DRIVE_FILE_ID)}")
    print(f"quarterly_folder: {drive_folder_url(QUARTERLY_DRIVE_FOLDER_ID)}")
    print(f"zip: {args.zip_name} member={args.zip_member}")
    print(f"q1_zip: {args.q1_zip_name} member={args.q1_zip_member} dest={DEFAULT_Q1_EXTRACTED_CSV}")
    if args.tail_trades:
        since = parse_iso_utc(args.tail_since)
        end = parse_iso_utc(args.tail_end)
        print(
            "trades:"
            f" {trades_request_url(args.pair, unix_seconds_to_ns(since.timestamp()))}"
            f" through {end.isoformat()}"
        )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.dry_run:
        dry_run_summary(args)
        return 0

    dest_dir = ohlcvt_dir(args.data_root)
    zip_path = dest_dir / args.zip_name
    csv_path = dest_dir / DEFAULT_EXTRACTED_CSV

    if not args.skip_ohlcvt:
        dest_dir.mkdir(parents=True, exist_ok=True)
        if not zip_path.exists() and not args.skip_download:
            print(f"downloading {args.zip_name} from {drive_file_view_url(COMPLETE_DRIVE_FILE_ID)}")
            try:
                download_google_drive_file(COMPLETE_DRIVE_FILE_ID, zip_path)
            except DriveQuotaError as exc:
                print(str(exc), file=sys.stderr)
                if not args.tail_trades:
                    return 2
        if zip_path.exists():
            if args.expected_sha256:
                digest = sha256_file(zip_path)
                if digest != args.expected_sha256.lower():
                    print(
                        f"sha256 mismatch: {digest} != {args.expected_sha256}",
                        file=sys.stderr,
                    )
                    return 3
            extract_zip_member(zip_path, args.zip_member, csv_path)
            print(f"extracted {csv_path}")
        elif not args.tail_trades:
            print(f"missing {zip_path}", file=sys.stderr)
            return 2
        q1_zip = dest_dir / args.q1_zip_name
        q1_csv = dest_dir / DEFAULT_Q1_EXTRACTED_CSV
        if q1_zip.exists():
            extract_zip_member(q1_zip, args.q1_zip_member, q1_csv)
            print(f"extracted {q1_csv}")

    if args.tail_trades:
        since_ns = unix_seconds_to_ns(parse_iso_utc(args.tail_since).timestamp())
        end_ns = unix_seconds_to_ns(parse_iso_utc(args.tail_end).timestamp())
        summary = fetch_trades_tail(
            out_dir=trades_dir(args.data_root, args.pair),
            pair=args.pair,
            since_ns=since_ns,
            end_ns=end_ns,
            prefix=args.page_prefix,
        )
        print(
            f"trades_tail: pages={summary['pages']} last_seq={summary['last_seq']} "
            f"since_ns={summary['since_ns']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
