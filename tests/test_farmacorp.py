import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

import pyarrow.parquet as pq
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

from pipelines.ingestion.bronze.extract import scrape_farmacorp as farmacorp
from pipelines.ingestion.bronze.load.upload_snapshot import upload_snapshot


def card(**changes) -> farmacorp.Card:
    result: farmacorp.Card = {
        "name": "Example product",
        "href": "/collections/ofertas/products/123",
        "brand": "Example",
        "current_price_text": "Ahora Bs139,91",
        "regular_price_text": "Antes Bs164,60",
        "discount_label": "Ahorra 15%",
        "availability_label": None,
        "image_url": "//farmacorp.com/example.jpg",
    }
    result.update(changes)
    return result


def observation(value: farmacorp.Card) -> farmacorp.Observation:
    return farmacorp.observation(
        value, category="Ofertas", page_url=farmacorp.BASE_URL + "/collections/ofertas",
        run_id="test", observed_at="2026-10-29T23:00:00+00:00",
    )


class PriceTests(unittest.TestCase):
    def test_bolivian_display_formats(self):
        for text, expected in [
            ("Ahora Bs139,91", "139.91"), ("Antes Bs1.234,56", "1234.56"),
            ("Bs0,43", "0.43"), ("Bs 1234,56", "1234.56"), ("Bs. 0,00", "0.00"),
        ]:
            with self.subTest(text=text):
                self.assertEqual(str(farmacorp.parse_price(text)), expected)

    def test_rejects_missing_ambiguous_or_foreign_prices(self):
        for text in ["13991", "Bs139.91", "Bs1,2", "$139,91", "", "Bs-1,00", "Bs1,00 Bs2,00"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                farmacorp.parse_price(text)

    def test_discounted_price_is_not_cents_or_regular_price(self):
        row = observation(card())
        self.assertEqual(row["price"], "164.60")
        self.assertEqual(row["discount_price"], "139.91")
        self.assertEqual(row["current_price"], "139.91")
        self.assertEqual(row["discount_percent"], "15.00")
        self.assertEqual(row["product_url"], "https://farmacorp.com/products/123")
        self.assertEqual(row["image_url"], "https://farmacorp.com/example.jpg")
        self.assertEqual(row["currency"], "BOB")
        self.assertEqual(row["category"], "Ofertas")
        self.assertEqual(row["category_url"], farmacorp.BASE_URL + "/collections/ofertas")

    def test_category_is_preserved_for_filtering(self):
        row = farmacorp.observation(
            card(), category="Cuidado Personal",
            page_url=farmacorp.BASE_URL + "/collections/self-care?page=2",
            run_id="test", observed_at="2026-10-29T23:00:00+00:00",
        )
        self.assertEqual(row["category"], "Cuidado Personal")
        self.assertEqual(row["category_url"], farmacorp.BASE_URL + "/collections/self-care")

    def test_no_discount_is_explicit_null(self):
        row = observation(card(regular_price_text=None, discount_label=None))
        self.assertEqual(row["price"], "139.91")
        self.assertIsNone(row["discount_price"])
        self.assertIsNone(row["discount_percent"])
        self.assertIsNone(row["availability_label"])

    def test_equal_comparison_price_is_not_a_discount(self):
        row = observation(card(regular_price_text="Antes Bs139,91", discount_label=None))
        self.assertIsNone(row["discount_price"])

    def test_generic_venta_badge_does_not_imply_a_discount(self):
        row = observation(card(
            current_price_text="Bs0,90", regular_price_text=None, discount_label="Venta",
        ))
        self.assertEqual(row["price"], "0.90")
        self.assertIsNone(row["discount_price"])
        self.assertIsNone(row["discount_percent"])
        self.assertEqual(row["discount_label"], "Venta")

    def test_multibuy_badge_preserves_displayed_unit_price(self):
        row = observation(card(
            name="Bebida Carbonatada Sirius Guarana Botella X 350Ml",
            href="/collections/lo-nuevo/products/7771621380859",
            current_price_text="Bs7,50", regular_price_text=None, discount_label="3 x 2",
        ))
        self.assertEqual(row["price"], "7.50")
        self.assertEqual(row["current_price"], "7.50")
        self.assertIsNone(row["discount_price"])
        self.assertIsNone(row["discount_percent"])
        self.assertEqual(row["discount_label"], "3 x 2")

    def test_invalid_promotion_still_fails(self):
        for label in ["Ahorra 15%", "3 x 0", "2 x 3", "3 x 3"]:
            with self.subTest(label=label), self.assertRaisesRegex(ValueError, "Discount label"):
                observation(card(regular_price_text=None, discount_label=label))

    def test_invalid_card_fails_instead_of_skipping(self):
        for changes in [
            {"name": None}, {"href": None}, {"current_price_text": None},
            {"regular_price_text": "Antes Bs1,00"},
            {"regular_price_text": None},
            {"href": "https://other.example/products/123"},
        ]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                observation(card(**changes))


class UrlAndPolicyTests(unittest.TestCase):
    def test_collection_validation(self):
        self.assertEqual(
            farmacorp.collection_url("/collections/ofertas?page=2&grid_list=grid-view"),
            farmacorp.BASE_URL + "/collections/ofertas?page=2&grid_list=grid-view",
        )
        self.assertEqual(
            farmacorp.collection_url("/collections/ofertas?page=3&grid_list"),
            farmacorp.BASE_URL + "/collections/ofertas?page=3&grid_list",
        )
        for url in [
            "https://other.example/collections/ofertas", "/cart", "/collections/ofertas/products/1",
            "/collections/ofertas?sort_by=price", "/collections/ofertas?page=0",
            "/collections/ofertas?page=1&page=2", "/collections/ofertas#x",
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                farmacorp.collection_url(url)

    def test_shopify_robots_wildcards_and_allow_priority(self):
        policy = farmacorp.RobotsPolicy(
            "User-agent: *\nAllow: /\nDisallow: /collections/*sort_by*\n"
            "Disallow: /account\nAllow: /account/login\nDisallow: /exact$\n"
            "User-agent: adsbot-google\nDisallow: /\n",
        )
        for path in ["/collections/ofertas?page=2", "/account/login", "/exactly"]:
            policy.check(farmacorp.BASE_URL + path)
        for path in ["/collections/ofertas?sort_by=price", "/account", "/exact"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                policy.check(farmacorp.BASE_URL + path)

    def test_specific_agent_group(self):
        policy = farmacorp.RobotsPolicy(
            "User-agent: *\nAllow: /\n"
            "User-agent: BoliviaPharmaPriceEngine\nDisallow: /collections\n",
        )
        with self.assertRaises(ValueError):
            policy.check(farmacorp.BASE_URL + "/collections/ofertas")


class PaginationTests(unittest.TestCase):
    def collect(self, pages):
        rows = []
        with patch.object(farmacorp, "navigate"), patch.object(
            farmacorp, "read_category", side_effect=pages,
        ):
            result = farmacorp.collect_category(
                MagicMock(), farmacorp.BASE_URL + "/collections/ofertas",
                farmacorp.RobotsPolicy("User-agent: *\nAllow: /"), 0,
                "test", rows.extend,
            )
        return result, rows

    def test_all_pages_and_total_count(self):
        result, rows = self.collect([
            ("Ofertas", 3, [card()], "/collections/ofertas?page=2&grid_list=grid-view"),
            ("Ofertas", 3, [card(href="/products/456")], "/collections/ofertas?page=3&grid_list"),
            ("Ofertas", 3, [card(href="/products/789")], None),
        ])
        self.assertEqual(result["pages"], 3)
        self.assertEqual(result["products"], 3)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1]["page_url"], farmacorp.BASE_URL + "/collections/ofertas?page=2&grid_list=grid-view")

    def test_empty_category(self):
        result, rows = self.collect([("Empty", 0, [], None)])
        self.assertEqual(result["products"], 0)
        self.assertEqual(rows, [])

    def test_multibuy_offer_is_collected_with_explicit_warning(self):
        result, rows = self.collect([
            ("LO NUEVO", 1, [card(
                current_price_text="Bs7,50", regular_price_text=None, discount_label="3 x 2",
            )], None),
        ])
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["discount_price"])
        self.assertTrue(any("3 x 2" in warning for warning in result["warnings"]))

    def test_terminal_empty_page_retains_prior_rows_and_warns(self):
        result, rows = self.collect([
            ("Medicamentos", 2, [card()], "/collections/ofertas?page=2"),
            ("Medicamentos", 2, [], None),
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(result["pages"], 2)
        self.assertTrue(any("explicit empty-results terminal page" in w for w in result["warnings"]))
        self.assertTrue(any("last advertised total 2" in w for w in result["warnings"]))

    def test_count_mismatch_has_explicit_warning(self):
        result, rows = self.collect([("Ofertas", 2, [card()], None)])
        self.assertEqual(len(rows), 1)
        self.assertIn("last advertised total 2", result["warnings"][0])

    def test_duplicate_products_retained_and_flagged(self):
        result, rows = self.collect([
            ("Ofertas", 2, [card()], "/collections/ofertas?page=2"),
            ("Ofertas", 2, [card()], None),
        ])
        self.assertEqual(len(rows), 2)
        self.assertEqual(result["products"], 1)
        self.assertIn("repeated products", result["warnings"][0])

    def test_count_changes_are_preserved_with_warnings(self):
        result, rows = self.collect([
            ("Ofertas", 2, [card()], "/collections/ofertas?page=2"),
            ("Ofertas", 3, [card(href="/products/456")], None),
        ])
        self.assertEqual(len(rows), 2)
        self.assertEqual(result["reported_totals"], [2, 3])
        self.assertIn("advertised total changed", result["warnings"][0])
        self.assertEqual(result["page_results"][1]["reported_total"], 3)

    def test_changed_category_name_fails(self):
        with self.assertRaisesRegex(ValueError, "Category name changed"):
            self.collect([
                ("Ofertas", 2, [card()], "/collections/ofertas?page=2"),
                ("Other", 2, [card(href="/products/456")], None),
            ])

    def test_invalid_next_page_fails(self):
        for url in ["/collections/ofertas", "/collections/ofertas?page=3", "/collections/other?page=2"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.collect([("Ofertas", 2, [card()], url)])

    def test_http_errors_and_wrong_redirects_fail(self):
        page = MagicMock()
        page.goto.return_value.status = 429
        policy = farmacorp.RobotsPolicy("User-agent: *\nAllow: /")
        with self.assertRaisesRegex(RuntimeError, "429"):
            farmacorp.navigate(page, farmacorp.BASE_URL + "/collections/ofertas", policy, 0)
        page.goto.return_value.status = 200
        page.url = farmacorp.BASE_URL + "/collections/ofertas"
        with self.assertRaisesRegex(RuntimeError, "redirect"):
            farmacorp.navigate(page, farmacorp.BASE_URL + "/collections/ofertas?page=2", policy, 0)


class OfflineBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def test_real_dom_extraction_excludes_recommendations_and_ambiguous_jsonld(self):
        page = self.browser.new_page()
        try:
            page.set_content("""
                <h1>Ofertas (1 producto)</h1>
                <div id="CategoriesNavPanel">
                  <a href="/collections/ofertas">Ofertas</a>
                  <a href="/collections/beauty">Belleza</a>
                  <a href="/collections/ofertas">Duplicate</a><a href="/pages/help">Help</a>
                </div>
                <li class="productgrid--item">
                  <h2 class="productitem--title"><a href="/collections/ofertas/products/123">Example product</a></h2>
                  <span class="productitem--vendor">Example</span>
                  <div class="price--compare-at"><span class="money">Antes Bs164,60</span></div>
                  <div class="price--main"><span class="money">Ahora Bs139,91</span></div>
                  <span class="badge--sale">Ahorra 15%</span>
                  <span class="badge--soldout">Agotado</span>
                  <img src="//farmacorp.com/example.jpg">
                </li>
                <div class="recommendations"><div class="price--main"><span class="money">Bs999,00</span></div></div>
                <script type="application/ld+json">{"price":"13991"}</script>
                <li class="pagination--next"><a href="/collections/ofertas?page=2">Siguiente</a></li>
            """)
            name, total, cards, next_url = farmacorp.read_category(page)
            self.assertEqual((name, total, len(cards), next_url), ("Ofertas", 1, 1, "/collections/ofertas?page=2"))
            row = observation(cards[0])
            self.assertEqual(row["discount_price"], "139.91")
            self.assertEqual(row["availability_label"], "Agotado")
            self.assertEqual(farmacorp.discover_categories(page), [
                farmacorp.BASE_URL + "/collections/ofertas", farmacorp.BASE_URL + "/collections/beauty",
            ])
        finally:
            page.close()

    def test_main_menu_discovery_excludes_nested_and_noncollection_links(self):
        page = self.browser.new_page()
        try:
            page.set_content("""
                <div id="CategoriesNavPanel">
                  <div class="mobile-nav-panel"><ul class="navmenu-depth-1">
                    <li><a href="/collections/ofertas">Ofertas</a></li>
                    <li><a href="/collections/beauty">Belleza</a>
                      <ul><li><a href="/collections/labios">Labios</a></li></ul>
                    </li>
                    <li><a href="/blogs/news">Blogs</a></li>
                  </ul></div>
                  <div><ul class="navmenu-depth-2">
                    <li><a href="/collections/hair">Cabello</a></li>
                  </ul></div>
                </div>
            """)
            self.assertEqual(farmacorp.discover_categories(page, main_only=True), [
                farmacorp.BASE_URL + "/collections/ofertas",
                farmacorp.BASE_URL + "/collections/beauty",
            ])
            self.assertEqual(len(farmacorp.discover_categories(page)), 4)
        finally:
            page.close()

    def test_multibuy_badge_from_dom_preserves_price(self):
        page = self.browser.new_page()
        try:
            page.set_content("""
                <h1>LO NUEVO (1 producto)</h1>
                <li class="productgrid--item">
                  <h2 class="productitem--title">
                    <a href="/collections/lo-nuevo/products/7771621380859">
                      Bebida Carbonatada Sirius Guarana Botella X 350Ml
                    </a>
                  </h2>
                  <div class="price--main"><span class="money">Bs7,50</span></div>
                  <span class="badge--sale">3 x 2</span>
                </li>
            """)
            _, _, cards, _ = farmacorp.read_category(page)
            self.assertEqual(cards[0]["discount_label"], "3 x 2")
            self.assertIsNone(cards[0]["regular_price_text"])
            row = observation(cards[0])
            self.assertEqual(row["price"], "7.50")
            self.assertIsNone(row["discount_price"])
        finally:
            page.close()

    def test_explicit_empty_terminal_page_with_nonzero_heading(self):
        page = self.browser.new_page()
        try:
            page.set_default_timeout(500)
            page.set_content("""
                <main><h1>Medicamentos (3800 productos)</h1>
                <h2 class="productgrid--no-results-title">No se encontro coincidencias</h2>
                </main>
            """)
            self.assertEqual(farmacorp.read_category(page), ("Medicamentos", 3800, [], None))
            page.locator("main").evaluate("""main => main.insertAdjacentHTML('beforeend',
                '<div class="pagination--next"><a href="/collections/medicamentos?page=162">Next</a></div>')""")
            with self.assertRaisesRegex(ValueError, "next-page"):
                farmacorp.read_category(page)
        finally:
            page.close()

    def test_unknown_empty_marker_does_not_establish_completion(self):
        page = self.browser.new_page()
        try:
            page.set_content("""
                <h1>Medicamentos (3800 productos)</h1>
                <h2 class="productgrid--no-results-title">Please try again</h2>
            """)
            with self.assertRaisesRegex(ValueError, "No product cards"):
                farmacorp.read_category(page)
        finally:
            page.close()


class OutputTests(unittest.TestCase):
    def test_category_timeout_restarts_pagination_and_retains_rows(self):
        url = farmacorp.BASE_URL + "/collections/ofertas"
        first = ("Ofertas", 2, [card()], url + "?page=2")
        last = ("Ofertas", 2, [card(href="/products/456")], None)
        for failures in (1, 2, 3):
            pages = []
            for _ in range(failures):
                pages.extend([first, PlaywrightTimeoutError("Page stalled")])
            if failures < 3:
                pages.extend([first, last])
            with self.subTest(failures=failures), TemporaryDirectory() as output, patch.object(
                farmacorp, "sync_playwright",
            ) as playwright, patch.object(farmacorp, "navigate") as navigate, patch.object(
                farmacorp, "read_category", side_effect=pages,
            ), patch("pipelines.ingestion.bronze.extract.category_retries.time.sleep") as pause:
                context = playwright.return_value.__enter__.return_value.chromium.launch.return_value.new_context.return_value
                context.request.get.return_value.status = 200
                context.request.get.return_value.text.return_value = "User-agent: *\nAllow: /"
                if failures == 3:
                    with self.assertRaises(PlaywrightTimeoutError):
                        farmacorp.run([url, farmacorp.BASE_URL + "/collections/beauty"], False, Path(output), 3)
                else:
                    farmacorp.run([url], False, Path(output), 3)
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
                self.assertEqual([call.args[1] for call in navigate.call_args_list], [url, url + "?page=2"] * attempts)
                self.assertEqual(pause.call_count, min(failures, 2))
                directory = next(Path(output).iterdir())
                rows = pq.read_table(directory / summary["output_files"]["parquet"]).to_pylist()
                self.assertEqual(len(rows), summary["observations"])
                self.assertEqual(sum(row["product_url"].endswith("/123") for row in rows), attempts)
                self.assertEqual(len(summary["categories"]), 0 if failures == 3 else 1)

    def test_non_timeout_category_failure_is_not_retried(self):
        with TemporaryDirectory() as output, patch.object(
            farmacorp, "sync_playwright",
        ) as playwright, patch.object(
            farmacorp, "collect_category", side_effect=ValueError("Invalid product"),
        ) as collect, patch("pipelines.ingestion.bronze.extract.category_retries.time.sleep") as pause:
            context = playwright.return_value.__enter__.return_value.chromium.launch.return_value.new_context.return_value
            context.request.get.return_value.status = 200
            context.request.get.return_value.text.return_value = "User-agent: *\nAllow: /"
            with self.assertRaisesRegex(ValueError, "Invalid product"):
                farmacorp.run([farmacorp.BASE_URL + "/collections/ofertas"], False, Path(output), 3)
            collect.assert_called_once()
            pause.assert_not_called()
            summary = json.loads(next(Path(output).glob("*/summary.json")).read_text())
            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["category_attempts"][0]["status"], "failed")

    def test_main_category_run_excludes_ofertas_and_keeps_csv_category(self):
        def write_category(page, url, policy, delay, run_id, write_rows):
            row = farmacorp.observation(
                card(), category="Beauty", page_url=url,
                run_id=run_id, observed_at="2026-10-29T23:00:00+00:00",
            )
            write_rows([row])
            return {"name": "Beauty", "warnings": []}

        with TemporaryDirectory() as output, patch.object(
            farmacorp, "sync_playwright",
        ) as playwright, patch.object(
            farmacorp, "discover_categories", return_value=[
                farmacorp.BASE_URL + "/collections/ofertas",
                farmacorp.BASE_URL + "/collections/beauty",
            ],
        ) as discover, patch.object(farmacorp, "navigate"), patch.object(
            farmacorp, "collect_category", side_effect=write_category,
        ) as collect:
            context = playwright.return_value.__enter__.return_value.chromium.launch.return_value.new_context.return_value
            context.request.get.return_value.status = 200
            context.request.get.return_value.text.return_value = "User-agent: *\nAllow: /"
            directory = farmacorp.run(
                [], False, Path(output), 0, main_categories=True,
                excluded_categories=[farmacorp.BASE_URL + "/collections/ofertas"],
            )
            discover.assert_called_once_with(context.new_page.return_value, main_only=True)
            self.assertEqual(collect.call_count, 1)
            self.assertEqual(collect.call_args.args[1], farmacorp.BASE_URL + "/collections/beauty")
            with next(directory.glob("scrape_farmacorp_*.csv")).open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["category"], "Beauty")
            summary = json.loads((directory / "summary.json").read_text())
            self.assertEqual(summary["requested_categories"], [
                farmacorp.BASE_URL + "/collections/beauty",
            ])
            self.assertIsNone(summary["active_category"])

    def test_completion_status_distinguishes_catalog_warnings(self):
        for warnings in [[], ["Advertised total changed"]]:
            with self.subTest(warnings=warnings), TemporaryDirectory() as output, patch.object(
                farmacorp, "sync_playwright",
            ) as playwright, patch.object(
                farmacorp, "collect_category", return_value={"warnings": warnings},
            ):
                context = playwright.return_value.__enter__.return_value.chromium.launch.return_value.new_context.return_value
                context.request.get.return_value.status = 200
                context.request.get.return_value.text.return_value = "User-agent: *\nAllow: /"
                directory = farmacorp.run(
                    [farmacorp.BASE_URL + "/collections/ofertas"], False, Path(output), 0,
                )
                playwright.return_value.__enter__.return_value.chromium.launch.return_value.new_context.assert_called_once_with(
                    locale="es-BO", timezone_id="America/La_Paz",
                )
                summary = json.loads((directory / "summary.json").read_text())
                self.assertEqual(
                    summary["status"], "completed_with_warnings" if warnings else "completed",
                )
                self.assertEqual(summary["categories"][0]["warnings"], warnings)
                self.assertEqual(
                    pq.read_table(directory / summary["output_files"]["parquet"]).num_rows, 0,
                )

    def test_robots_failure_prevents_collection(self):
        with TemporaryDirectory() as output, patch.object(
            farmacorp, "sync_playwright",
        ) as playwright, patch.object(farmacorp, "collect_category") as collect:
            context = playwright.return_value.__enter__.return_value.chromium.launch.return_value.new_context.return_value
            context.request.get.return_value.status = 503
            with self.assertRaisesRegex(RuntimeError, "robots.txt"):
                farmacorp.run([farmacorp.BASE_URL + "/collections/ofertas"], False, Path(output), 0)
            collect.assert_not_called()
            summary_path = next(Path(output).glob("*/summary.json"))
            self.assertEqual(json.loads(summary_path.read_text())["status"], "failed")

    def test_failed_run_keeps_rows_but_marks_incomplete(self):
        def fail_after_page(page, url, policy, delay, run_id, write_rows):
            write_rows([observation(card())])
            raise RuntimeError("Interrupted page two")

        with TemporaryDirectory() as output, patch.object(
            farmacorp, "sync_playwright",
        ) as playwright, patch.object(farmacorp, "collect_category", side_effect=fail_after_page):
            context = playwright.return_value.__enter__.return_value.chromium.launch.return_value.new_context.return_value
            context.request.get.return_value.status = 200
            context.request.get.return_value.text.return_value = "User-agent: *\nAllow: /"
            with self.assertRaisesRegex(RuntimeError, "Interrupted"):
                farmacorp.run([farmacorp.BASE_URL + "/collections/ofertas"], False, Path(output), 0)
            directory = next(Path(output).iterdir())
            summary = json.loads((directory / "summary.json").read_text())
            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["observations"], 1)
            self.assertIn("Interrupted", summary["error"])
            rows = [
                json.loads(line) for line in
                (directory / summary["output_files"]["jsonl"]).read_text().splitlines()
            ]
            with (directory / summary["output_files"]["csv"]).open() as stream:
                csv_rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 1)
            self.assertEqual(csv_rows[0]["discount_price"], "139.91")
            self.assertEqual(
                pq.read_table(directory / summary["output_files"]["parquet"]).to_pylist(), rows,
            )

    def test_timestamped_outputs_match_across_formats_and_batches(self):
        expected = [
            observation(card()),
            observation(card(
                name="Cuidado personal", href="/products/456",
                regular_price_text=None, discount_label=None,
            )),
        ]

        def write_category(page, url, policy, delay, run_id, write_rows):
            for row in expected:
                row["run_id"] = run_id
                write_rows([row])
            return {"warnings": []}

        with TemporaryDirectory() as output, patch.object(
            farmacorp, "sync_playwright",
        ) as playwright, patch.object(
            farmacorp, "collect_category", side_effect=write_category,
        ):
            context = playwright.return_value.__enter__.return_value.chromium.launch.return_value.new_context.return_value
            context.request.get.return_value.status = 200
            context.request.get.return_value.text.return_value = "User-agent: *\nAllow: /"
            directory = farmacorp.run(
                [farmacorp.BASE_URL + "/collections/ofertas"], False, Path(output), 0,
            )
            summary = json.loads((directory / "summary.json").read_text())
            self.assertEqual(summary["retailer"], "farmacorp")
            for extension, name in summary["output_files"].items():
                self.assertRegex(name, rf"^scrape_farmacorp_\d{{8}}T\d{{6}}Z\.{extension}$")
                self.assertEqual(name, f"scrape_farmacorp_{summary['run_id'].split('_')[0]}.{extension}")
            self.assertFalse((directory / "observations.csv").exists())
            self.assertFalse((directory / "observations.jsonl").exists())
            json_rows = [
                json.loads(line) for line in
                (directory / summary["output_files"]["jsonl"]).read_text().splitlines()
            ]
            table = pq.read_table(directory / summary["output_files"]["parquet"])
            self.assertEqual(table.to_pylist(), expected)
            self.assertEqual(json_rows, expected)
            self.assertEqual(table.column_names, list(farmacorp.Observation.__annotations__))
            self.assertEqual(summary["observations"], 2)
            with patch("pipelines.ingestion.bronze.load.upload_snapshot.BlobServiceClient.from_connection_string"):
                uploaded = upload_snapshot(directory, "farmacorp", "test-connection", "test-container")
            self.assertEqual(len(uploaded), 1)
            self.assertTrue(uploaded[0].endswith(".parquet"))
            self.assertTrue(all(path.startswith(f"farmacorp/{summary['run_id'][:8]}/") for path in uploaded))
            with (directory / summary["output_files"]["csv"]).open() as stream:
                csv_rows = list(csv.DictReader(stream))
            for expected_row, csv_row in zip(expected, csv_rows):
                self.assertEqual(
                    csv_row,
                    {key: "" if value is None else value for key, value in expected_row.items()},
                )


if __name__ == "__main__":
    unittest.main()
