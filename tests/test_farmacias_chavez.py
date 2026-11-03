import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch
from urllib.robotparser import RobotFileParser

import pyarrow.parquet as pq
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

from pipelines.ingestion.bronze.extract import scrape_farmacias_chavez as chavez
from pipelines.ingestion.bronze.extract.snapshot import SnapshotWriter


def card():
    return {
        "href": "/p/example-product-123", "name": "Full product name",
        "display_name": "Full product...", "current_price_text": "Bs 9,75",
        "regular_price_text": "(Bs 11,9)", "discount_label": "Ahorra 18%",
        "availability_label": None, "image_url": "https://example.com/image.jpg",
    }


def make_row(value):
    return chavez.observation(
        value, "Ofertas Del Mes", chavez.BASE_URL + "/ca/ofertas-del-mes/114",
        chavez.BASE_URL + "/ca/ofertas-del-mes/114", "test", "2026-10-30T16:00:00+00:00",
    )


class PriceTests(unittest.TestCase):
    def test_local_prices(self):
        for value, expected in [
            ("Bs 9,75", "9.75"), ("(Bs 11,9)", "11.9"), ("Bs 11", "11.0"),
            ("Bs 1.234,56", "1234.56"), ("Bs 0", "0.0"),
        ]:
            with self.subTest(value=value):
                self.assertEqual(str(chavez.parse_price(value)), expected)

    def test_bad_prices(self):
        for value in ["", "$ 3", "Bs -2", "Bs 1.25", "Bs 1,234"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                chavez.parse_price(value)

    def test_discount_and_full_name(self):
        row = make_row(card())
        self.assertEqual(row["price"], "11.90")
        self.assertEqual(row["discount_price"], "9.75")
        self.assertEqual(row["name"], "Full product name")
        self.assertEqual(row["display_name"], "Full product...")
        self.assertEqual(row["product_id"], "123")
        self.assertEqual(row["category"], "Ofertas Del Mes")
        self.assertIsNone(row["availability_label"])

    def test_plain_price(self):
        value = card()
        value["regular_price_text"] = None
        value["discount_label"] = None
        row = make_row(value)
        self.assertEqual(row["price"], "9.75")
        self.assertIsNone(row["discount_price"])

    def test_missing_fields_and_inverted_prices_fail(self):
        for changes in [
            {"name": None}, {"href": None}, {"current_price_text": None},
            {"regular_price_text": "(Bs 1)"}, {"href": "https://other.example/p/x-123"},
        ]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                make_row(card() | changes)

    def test_urls_refuse_transactional_and_external_paths(self):
        for url in ["/cart", "https://other.example/ca/test/1", "/ca/test/1?sort=price"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                chavez.public_url(url, "category")


class PolicyTests(unittest.TestCase):
    def context(self, status=200, text="User-agent: *\nDisallow: /cart", content_type="text/plain"):
        context = MagicMock()
        response = context.request.get.return_value
        response.status = status
        response.text.return_value = text
        response.headers = {"content-type": content_type}
        return context

    def test_valid_rules(self):
        policy, warnings = chavez.check_robots(self.context(), False)
        self.assertTrue(policy.can_fetch(chavez.USER_AGENT, chavez.BASE_URL + "/ca/test/1"))
        self.assertFalse(policy.can_fetch(chavez.USER_AGENT, chavez.BASE_URL + "/cart"))
        self.assertEqual(warnings, [])

    def test_html_requires_explicit_approval(self):
        context = self.context(text="<!DOCTYPE html><html>", content_type="text/html")
        with self.assertRaisesRegex(RuntimeError, "approval"):
            chavez.check_robots(context, False)
        policy, warnings = chavez.check_robots(context, True)
        self.assertEqual(len(warnings), 1)
        self.assertTrue(policy.can_fetch(chavez.USER_AGENT, chavez.BASE_URL))

    def test_server_errors_are_not_missing_rules(self):
        for status in [403, 429, 500]:
            with self.subTest(status=status), self.assertRaises(RuntimeError):
                chavez.check_robots(self.context(status=status), True)


class LocalBrowserTests(unittest.TestCase):
    def test_category_url_is_read_after_client_navigation_finishes(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()
                page.route("**/*", lambda route: route.fulfill(
                    content_type="text/html", body="""
                    <h1>Old</h1><div class="category-tree-modal">
                    <button onclick="setTimeout(() => {
                      history.pushState({}, '', '/ca/new/2');
                      document.querySelector('h1').textContent = 'New';
                    }, 100)">New</button></div>
                    """,
                ))
                page.goto(chavez.BASE_URL + "/ca/old/1")
                self.assertEqual(chavez.open_category(page, "New", 0), chavez.BASE_URL + "/ca/new/2")
            finally:
                browser.close()

    def test_local_card_and_pagination_dom(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()
                page.set_content("""
                  <div><h1>Ofertas Del Mes</h1><p>(100)</p></div>
                  <a class="containerCard" href="/p/example-product-123">
                    <img alt="Full product name" src="https://example.com/image.jpg">
                    <button class="styles__PromoTagStyles">Ahorra 18%</button>
                    <p class="base__price" data-testid="crossed-out-current">Bs 9,75</p>
                    <p data-testid="crossed-out-old">(Bs 11,9)</p>
                    <h3 data-testid="card-name">Full product...</h3>
                  </a>
                  <li class="ant-pagination-simple-pager" title="1/2"></li>
                """)
                total, cards, current, last = chavez.read_page(page)
                self.assertEqual((total, current, last), (100, 1, 2))
                self.assertEqual(make_row(cards[0])["discount_price"], "9.75")
                self.assertEqual(cards[0]["name"], "Full product name")
                self.assertEqual(cards[0]["discount_label"], "Ahorra 18%")
            finally:
                browser.close()


class TraversalTests(unittest.TestCase):
    def collect(self, pages):
        page = MagicMock()
        page.url = chavez.BASE_URL + "/ca/test/1"
        policy = RobotFileParser()
        policy.parse(["User-agent: *", "Allow: /"])
        page.locator.return_value.count.return_value = 1
        page.locator.return_value.get_attribute.return_value = "true"
        rows = []
        with patch.object(chavez, "open_category", return_value=page.url), patch.object(
            chavez, "read_page", side_effect=pages,
        ), patch.object(chavez.time, "sleep"):
            result = chavez.collect_category(page, "Test", policy, 0, "test", rows.extend)
        return result, rows, page

    def test_all_pages(self):
        result, rows, page = self.collect([
            (2, [card()], 1, 2),
            (2, [card() | {"href": "/p/other-456"}], 2, 2),
        ])
        self.assertEqual(result["pages"], 2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(result["products"], 2)
        page.wait_for_url.assert_called_once_with(chavez.BASE_URL + "/ca/test/1?currentPage=2")

    def test_repeated_full_page_fails(self):
        with self.assertRaisesRegex(ValueError, "Repeated full page"):
            self.collect([(2, [card()], 1, 2), (2, [card()], 2, 2)])

    def test_bad_page_progression_fails(self):
        with self.assertRaisesRegex(ValueError, "Unexpected page"):
            self.collect([(1, [card()], 2, 2)])

    def test_empty_category(self):
        result, rows, _ = self.collect([(0, [], 1, 1)])
        self.assertEqual(result["products"], 0)
        self.assertEqual(rows, [])

    def test_count_changes_are_flagged(self):
        result, rows, _ = self.collect([
            (2, [card()], 1, 2),
            (3, [card() | {"href": "/p/other-456"}], 2, 2),
        ])
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(result["warnings"]), 2)


class SnapshotTests(unittest.TestCase):
    def test_category_timeout_restarts_pagination_and_retains_rows(self):
        url = chavez.BASE_URL + "/ca/test/1"
        policy = RobotFileParser()
        policy.parse(["User-agent: *", "Allow: /"])
        first = (2, [card()], 1, 2)
        last = (2, [card() | {"href": "/p/other-456"}], 2, 2)
        for failures in (1, 2, 3):
            pages = []
            for _ in range(failures):
                pages.extend([first, PlaywrightTimeoutError("Page stalled")])
            if failures < 3:
                pages.extend([first, last])
            with self.subTest(failures=failures), TemporaryDirectory() as output, patch.object(
                chavez, "sync_playwright",
            ) as playwright, patch.object(chavez, "navigate") as navigate, patch.object(
                chavez, "discover_names", return_value=["Test", "Other"],
            ), patch.object(chavez, "check_robots", return_value=(policy, [])), patch.object(
                chavez, "open_category", return_value=url,
            ) as open_category, patch.object(
                chavez, "read_page", side_effect=pages,
            ), patch("pipelines.ingestion.bronze.extract.category_retries.time.sleep") as pause:
                page = playwright.return_value.__enter__.return_value.chromium.launch.return_value.new_context.return_value.new_page.return_value
                page.url = url
                page.locator.return_value.count.return_value = 1
                page.locator.return_value.get_attribute.return_value = "true"
                if failures == 3:
                    with self.assertRaises(PlaywrightTimeoutError):
                        chavez.run(Path(output), ["Test", "Other"], 3, False)
                else:
                    chavez.run(Path(output), ["Test"], 3, False)
                summary = json.loads(next(Path(output).glob("*/summary.json")).read_text())
                attempts = min(failures + 1, 3)
                self.assertEqual(summary["category_timeout_retries"], 2)
                self.assertEqual(len(summary["category_attempts"]), attempts)
                self.assertEqual(
                    [a["status"] for a in summary["category_attempts"]],
                    ["timed_out"] * failures + (["completed"] if failures < 3 else []),
                )
                self.assertEqual(
                    [a["observations"] for a in summary["category_attempts"]],
                    [1] * failures + ([2] if failures < 3 else []),
                )
                self.assertEqual(summary["observations"], failures + (2 if failures < 3 else 0))
                self.assertEqual(
                    summary["status"], "failed" if failures == 3 else "completed_with_warnings",
                )
                self.assertEqual(open_category.call_count, attempts)
                self.assertTrue(all(call.args[1] == "Test" for call in open_category.call_args_list))
                self.assertEqual(navigate.call_count, attempts)
                self.assertTrue(all(call.args[1] == chavez.BASE_URL + "/" for call in navigate.call_args_list))
                # Page pacing also calls time.sleep; count only the retry pauses.
                self.assertEqual(sum(call.args[0] >= 10 for call in pause.call_args_list), min(failures, 2))
                directory = next(Path(output).iterdir())
                rows = pq.read_table(directory / summary["output_files"]["parquet"]).to_pylist()
                self.assertEqual(len(rows), summary["observations"])
                self.assertEqual(sum(row["product_id"] == "123" for row in rows), attempts)
                self.assertEqual(len(summary["categories"]), 0 if failures == 3 else 1)

    def test_non_timeout_category_failure_is_not_retried(self):
        with TemporaryDirectory() as output, patch.object(
            chavez, "sync_playwright",
        ), patch.object(chavez, "check_robots", return_value=(MagicMock(), [])), patch.object(
            chavez, "navigate",
        ), patch.object(chavez, "discover_names", return_value=["Test"]), patch.object(
            chavez, "collect_category", side_effect=ValueError("Invalid product"),
        ) as collect, patch("pipelines.ingestion.bronze.extract.category_retries.time.sleep") as pause:
            with self.assertRaisesRegex(ValueError, "Invalid product"):
                chavez.run(Path(output), None, 3, False)
            collect.assert_called_once()
            pause.assert_not_called()
            summary = json.loads(next(Path(output).glob("*/summary.json")).read_text())
            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["category_attempts"][0]["status"], "failed")

    def test_formats_and_nulls_match_on_failure(self):
        row = make_row(card())
        with TemporaryDirectory() as output:
            snapshot = SnapshotWriter(Path(output), "scrape_farmacias_chavez_20261030T160000Z", chavez.FIELDS)
            with self.assertRaisesRegex(RuntimeError, "test"):
                with snapshot:
                    snapshot.write([row])
                    raise RuntimeError("test")
            json_rows = [
                json.loads(line) for line in
                (Path(output) / snapshot.files["jsonl"]).read_text().splitlines()
            ]
            self.assertEqual(pq.read_table(Path(output) / snapshot.files["parquet"]).to_pylist(), json_rows)
            with (Path(output) / snapshot.files["csv"]).open() as stream:
                csv_rows = list(csv.DictReader(stream))
            self.assertEqual(csv_rows[0]["category"], row["category"])
            self.assertEqual(csv_rows[0]["price"], "11.90")

    def test_run_failure_records_error_and_closes_browser(self):
        with TemporaryDirectory() as output, patch.object(
            chavez, "sync_playwright",
        ) as playwright, patch.object(chavez, "check_robots", side_effect=RuntimeError("policy error")):
            with self.assertRaisesRegex(RuntimeError, "policy error"):
                chavez.run(Path(output), None, 0, False)
            playwright.return_value.__enter__.return_value.chromium.launch.return_value.new_context.assert_called_once_with(
                locale="es-BO", timezone_id="America/La_Paz",
            )
            summary = json.loads(next(Path(output).glob("*/summary.json")).read_text())
            self.assertEqual(summary["retailer"], "farmacias_chavez")
            self.assertEqual(summary["status"], "failed")
            self.assertIn("policy error", summary["error"])
            playwright.return_value.__enter__.return_value.chromium.launch.return_value.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
