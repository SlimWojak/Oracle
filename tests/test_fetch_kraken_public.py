import importlib.util
import unittest
from pathlib import Path


def load_fetch_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "fetch_kraken_public.py"
    spec = importlib.util.spec_from_file_location("fetch_kraken_public", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module from {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch = load_fetch_module()


class DriveUrlTests(unittest.TestCase):
    def test_file_and_folder_urls(self) -> None:
        self.assertEqual(
            fetch.drive_file_view_url("1ptNqWYidLkhb2VAKuLCxmp2OXEfGO-AP"),
            "https://drive.google.com/file/d/1ptNqWYidLkhb2VAKuLCxmp2OXEfGO-AP/view?usp=sharing",
        )
        self.assertEqual(
            fetch.drive_folder_url("15RSlNuW_h0kVM8or8McOGOMfHeBFvFGI"),
            "https://drive.google.com/drive/folders/15RSlNuW_h0kVM8or8McOGOMfHeBFvFGI?usp=sharing",
        )

    def test_uc_url_with_and_without_confirm(self) -> None:
        self.assertEqual(
            fetch.drive_uc_url("abc123"),
            "https://drive.google.com/uc?export=download&id=abc123",
        )
        self.assertEqual(
            fetch.drive_uc_url("abc123", confirm="t"),
            "https://drive.google.com/uc?export=download&id=abc123&confirm=t",
        )


class SupportArticleParseTests(unittest.TestCase):
    def test_extracts_complete_file_and_quarterly_folder(self) -> None:
        html = (
            '<a href="https://drive.google.com/file/d/1ptNqWYidLkhb2VAKuLCxmp2OXEfGO-AP/'
            'view?usp=sharing"><strong>Single ZIP File</strong></a>'
            '<a href="https://drive.google.com/drive/folders/'
            '15RSlNuW_h0kVM8or8McOGOMfHeBFvFGI?usp=sharing">'
            "<strong>Quarterly ZIP Files</strong></a>"
        )
        parsed = fetch.parse_support_article_drive_links(html)
        self.assertEqual(parsed["complete_file_id"], "1ptNqWYidLkhb2VAKuLCxmp2OXEfGO-AP")
        self.assertEqual(parsed["quarterly_folder_id"], "15RSlNuW_h0kVM8or8McOGOMfHeBFvFGI")

    def test_missing_links_raise(self) -> None:
        with self.assertRaises(ValueError):
            fetch.parse_support_article_drive_links("<p>no drive links</p>")


class DriveFolderParseTests(unittest.TestCase):
    def test_pairs_ids_with_quarterly_zip_names(self) -> None:
        html = (
            'data-id="15QxEf_-rRS-Yt7uERCI41HMcQQPKzSHq-0-16">'
            "Kraken_OHLCVT_Q1_2026.zip</div>"
            'data-id="1QbPHLP0TTGo-lqwKn8M-_Xo_oexXlEnB-0-16">'
            "Kraken_OHLCVT_Q4_2025.zip</div>"
        )
        entries = fetch.parse_drive_folder_zip_entries(html)
        self.assertEqual(
            entries,
            [
                ("Kraken_OHLCVT_Q1_2026.zip", "15QxEf_-rRS-Yt7uERCI41HMcQQPKzSHq"),
                ("Kraken_OHLCVT_Q4_2025.zip", "1QbPHLP0TTGo-lqwKn8M-_Xo_oexXlEnB"),
            ],
        )


class DriveConfirmFormTests(unittest.TestCase):
    def test_hidden_fields_and_action(self) -> None:
        html = """
        <form id="download-form" action="https://drive.usercontent.google.com/download">
          <input type="hidden" name="id" value="fileid">
          <input type="hidden" name="export" value="download">
          <input type="hidden" name="confirm" value="t">
          <input type="hidden" name="uuid" value="abc-123">
        </form>
        """
        form = fetch.parse_drive_confirm_form(html)
        self.assertEqual(form["action"], "https://drive.usercontent.google.com/download")
        self.assertEqual(form["id"], "fileid")
        self.assertEqual(form["confirm"], "t")
        self.assertEqual(form["uuid"], "abc-123")
        url = fetch.confirm_form_download_url(form)
        self.assertTrue(url.startswith("https://drive.usercontent.google.com/download?"))
        self.assertIn("id=fileid", url)
        self.assertIn("confirm=t", url)


class TradesUrlAndCursorTests(unittest.TestCase):
    def test_request_url(self) -> None:
        url = fetch.trades_request_url("XBTUSD", 1775001600000000000, count=1000)
        self.assertEqual(
            url,
            "https://api.kraken.com/0/public/Trades?pair=XBTUSD"
            "&since=1775001600000000000&count=1000",
        )

    def test_unix_seconds_to_ns(self) -> None:
        self.assertEqual(fetch.unix_seconds_to_ns(1775001600), 1775001600000000000)

    def test_parse_page_and_advance_cursor(self) -> None:
        payload = {
            "error": [],
            "result": {
                "XXBTZUSD": [
                    ["68219.70000", "0.00014586", 1775001600.173861, "b", "l", "", 98121256]
                ],
                "last": "1775001600355552844",
            },
        }
        parsed = fetch.parse_trades_page(payload)
        self.assertEqual(parsed["pair_key"], "XXBTZUSD")
        self.assertEqual(parsed["trade_count"], 1)
        self.assertEqual(parsed["last"], "1775001600355552844")
        self.assertEqual(parsed["errors"], [])
        nxt = fetch.next_trades_since(parsed["last"], 1775001600000000000)
        self.assertEqual(nxt, 1775001600355552844)

    def test_stuck_or_missing_cursor_stops(self) -> None:
        self.assertIsNone(fetch.next_trades_since(None, 1))
        self.assertIsNone(fetch.next_trades_since("100", 100))
        self.assertIsNone(fetch.next_trades_since("99", 100))

    def test_rate_limit_errors_are_surfaced(self) -> None:
        parsed = fetch.parse_trades_page({"error": ["EAPI:Rate limit exceeded"], "result": {}})
        self.assertEqual(parsed["errors"], ["EAPI:Rate limit exceeded"])
        self.assertEqual(parsed["trade_count"], 0)
        self.assertIsNone(parsed["last"])


class ZipMemberAndCoverageTests(unittest.TestCase):
    def test_pair_csv_name(self) -> None:
        self.assertEqual(fetch.pair_csv_name("XBTUSD", 1), "XBTUSD_1.csv")

    def test_quarterly_csv_name_does_not_clobber_master(self) -> None:
        self.assertEqual(
            fetch.quarterly_csv_name("XBTUSD", 1, "Q1_2026"),
            "XBTUSD_1_Q1_2026.csv",
        )
        self.assertNotEqual(
            fetch.quarterly_csv_name("XBTUSD", 1, "Q1_2026"),
            fetch.pair_csv_name("XBTUSD", 1),
        )

    def test_find_zip_member_root_level_quarterly(self) -> None:
        self.assertEqual(
            fetch.find_zip_member(["AIXBTUSD_1.csv", "XBTUSD_1.csv"], "XBTUSD_1.csv"),
            "XBTUSD_1.csv",
        )

    def test_find_zip_member_prefers_master_q4(self) -> None:
        names = [
            "__MACOSX/master_q4/._XBTUSD_1.csv",
            "older/XBTUSD_1.csv",
            "master_q4/XBTUSD_1.csv",
        ]
        self.assertEqual(fetch.find_zip_member(names, "XBTUSD_1.csv"), "master_q4/XBTUSD_1.csv")

    def test_find_zip_member_exact_path(self) -> None:
        names = ["master_q4/XBTUSD_1.csv"]
        self.assertEqual(
            fetch.find_zip_member(names, "master_q4/XBTUSD_1.csv"),
            "master_q4/XBTUSD_1.csv",
        )

    def test_find_zip_member_missing(self) -> None:
        self.assertIsNone(fetch.find_zip_member(["ETHUSD_1.csv"], "XBTUSD_1.csv"))

    def test_theoretical_minutes(self) -> None:
        self.assertEqual(fetch.theoretical_minutes(2020), 527040)
        self.assertEqual(fetch.theoretical_minutes(2021), 525600)
        self.assertEqual(fetch.theoretical_minutes(2024), 527040)
        self.assertEqual(fetch.theoretical_minutes(2026), 305280)


if __name__ == "__main__":
    unittest.main()
