import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

import pyarrow.parquet as pq
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

from pipelines.ingestion.bronze import scrape_hipermaxi as hipermaxi
from pipelines.ingestion.bronze.snapshot import SnapshotWriter


def card():
    return {
        "href": hipermaxi.BRANCH_PATH + "/producto/123/example",
        "name": "Example", "current_price_text": "Bs 396.90",
        "regular_price_text": "Bs 529.30", "discount_label": "-25% OFF",
        "availability_label": None, "image_url": "/image.jpg",
    }


def policy():
    return hipermaxi.RobotsPolicy("User-agent: *\nAllow: /\nDisallow: /private/")


class ObservationTests(unittest.TestCase):
    def row(self, value):
        return hipermaxi.observation(
            value, "Farmacia Genéricos", hipermaxi.BRANCH_URL + "/categoria/farmacia-genericos",
            1, "test", "2026-10-30T16:00:00+00:00",
        )

    def test_exact_prices_and_discounts(self):
        row = self.row(card())
        self.assertEqual(row["price"], "529.30")
        self.assertEqual(row["discount_price"], "396.90")
        self.assertEqual(row["city"], "La Paz")
        self.assertEqual(row["branch"], "Farmacia Calacoto")
        self.assertEqual(row["product_id"], "123")
        self.assertEqual(row["batch"], "1")

    def test_plain_prices_and_nulls(self):
        row = self.row(card() | {"regular_price_text": None, "discount_label": None})
        self.assertEqual(row["price"], row["current_price"])
        self.assertIsNone(row["discount_price"])
        self.assertIsNone(row["availability_label"])

    def test_bob_format(self):
        self.assertEqual(str(hipermaxi.parse_price("Bs 1,234.56")), "1234.56")
        for text in ["Bs 9,75", "$ 3.00", "Bs -3.00", "Bs 3", ""]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                hipermaxi.parse_price(text)

    def test_invalid_cards_fail(self):
        for changes in [
            {"name": None}, {"href": "https://example.com/product/1"},
            {"current_price_text": None}, {"regular_price_text": "Bs 1.00"},
            {"regular_price_text": None},
        ]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.row(card() | changes)

    def test_branch_bound_category_urls(self):
        self.assertEqual(
            hipermaxi.category_url(hipermaxi.BRANCH_PATH + "/categoria/farmacia-genericos"),
            hipermaxi.BRANCH_URL + "/categoria/farmacia-genericos",
        )
        for url in [
            "/la-paz/supermercado/categoria/alimentos",
            hipermaxi.BRANCH_PATH + "/categoria/main/nested",
            hipermaxi.BRANCH_PATH + "/categoria/main?sort=price",
            "https://other.example" + hipermaxi.BRANCH_PATH + "/categoria/main",
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                hipermaxi.category_url(url)


class NavigationTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(hipermaxi, "pause")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_interactive_validation_returns_in_same_page(self):
        page = MagicMock()
        page.goto.return_value.status = 403
        page.url = "https://validate.perfdrive.com/?private_challenge=value"

        def finish_validation(*_args, **_kwargs):
            page.url = hipermaxi.BRANCH_URL

        page.wait_for_url.side_effect = finish_validation
        with self.assertLogs(hipermaxi.LOGGER, level="INFO") as logs:
            hipermaxi.navigate(page, hipermaxi.BRANCH_URL, policy(), 0, 60)
        page.bring_to_front.assert_called_once()
        self.assertEqual(page.wait_for_url.call_args.kwargs["timeout"], 60_000)
        self.assertNotIn("private_challenge", "\n".join(logs.output))
        page.goto.assert_called_once()

    def test_manual_validation_timeout_fails(self):
        page = MagicMock()
        page.url = "https://validate.perfdrive.com/"
        page.wait_for_url.side_effect = PlaywrightTimeoutError("secret URL")
        with self.assertLogs(hipermaxi.LOGGER), self.assertRaisesRegex(RuntimeError, "timed out") as error:
            hipermaxi.wait_for_catalog(page, policy(), 1)
        self.assertNotIn("secret", str(error.exception))

    def test_window_close_is_not_swallowed(self):
        page = MagicMock()
        page.url = "https://validate.perfdrive.com/"
        page.wait_for_url.side_effect = hipermaxi.PlaywrightError("Page closed")
        with self.assertLogs(hipermaxi.LOGGER), self.assertRaisesRegex(hipermaxi.PlaywrightError, "Page closed"):
            hipermaxi.wait_for_catalog(page, policy(), 1)

    def test_unexpected_return_and_robots_denial_stop(self):
        for destination in ["https://other.example/", hipermaxi.BRANCH_URL + "/forbidden"]:
            with self.subTest(destination=destination):
                page = MagicMock()
                page.url = "https://validate.perfdrive.com/"
                page.wait_for_url.side_effect = lambda *_a, **_kw: setattr(page, "url", destination)
                rules = hipermaxi.RobotsPolicy(
                    "User-agent: *\nDisallow: " + hipermaxi.BRANCH_PATH + "/forbidden",
                )
                with self.assertLogs(hipermaxi.LOGGER), self.assertRaises((RuntimeError, ValueError)):
                    hipermaxi.wait_for_catalog(page, rules, 1)

    def test_only_exact_validation_host_allowed_when_interactive(self):
        challenge = "https://validate.perfdrive.com/?challenge=private"
        with self.assertLogs(hipermaxi.LOGGER):
            self.assertFalse(hipermaxi.permitted_navigation(challenge, policy(), False))
        self.assertTrue(hipermaxi.permitted_navigation(challenge, policy(), True))
        for url in [
            "http://validate.perfdrive.com/",
            "https://validate.perfdrive.com.other.example/",
            "https://www.hipermaxi.com" + hipermaxi.BRANCH_PATH + "-other",
            "https://www.hipermaxi.com/la-paz/another-store",
        ]:
            with self.subTest(url=url), self.assertLogs(hipermaxi.LOGGER):
                self.assertFalse(hipermaxi.permitted_navigation(url, policy(), True))

    def test_interrupted_dom_action_retries_after_manual_return(self):
        page = MagicMock()
        page.url = hipermaxi.BRANCH_URL

        def interrupted():
            page.url = "https://validate.perfdrive.com/"
            raise PlaywrightTimeoutError("Interrupted")

        page.wait_for_url.side_effect = lambda *_a, **_kw: setattr(page, "url", hipermaxi.BRANCH_URL)
        attempts = 0

        def extract():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                interrupted()
            return ["product"]

        with self.assertLogs(hipermaxi.LOGGER):
            self.assertEqual(hipermaxi.catalog_action(page, policy(), 1, extract), ["product"])
        self.assertEqual(attempts, 2)

    def test_repeated_validation_does_not_retry_forever(self):
        page = MagicMock()
        page.url = hipermaxi.BRANCH_URL
        page.wait_for_url.side_effect = lambda *_a, **_kw: setattr(page, "url", hipermaxi.BRANCH_URL)

        def action():
            page.url = "https://validate.perfdrive.com/"
            return "not catalog data"

        with self.assertLogs(hipermaxi.LOGGER), self.assertRaisesRegex(RuntimeError, "Validation recurred"):
            hipermaxi.catalog_action(page, policy(), 1, action)
        self.assertEqual(page.wait_for_url.call_count, 2)

    def test_bot_validation_stops_without_bypass(self):
        page = MagicMock()
        page.goto.return_value.status = 200
        page.url = "https://validate.perfdrive.com/?private_challenge=value"
        with self.assertRaisesRegex(RuntimeError, "No validation bypass") as result:
            hipermaxi.navigate(page, hipermaxi.BRANCH_URL, policy(), 0)
        self.assertNotIn("private_challenge", str(result.exception))

    def test_http_errors_stop(self):
        page = MagicMock()
        page.url = hipermaxi.BRANCH_URL
        page.goto.return_value.status = 429
        with self.assertRaisesRegex(RuntimeError, "429"):
            hipermaxi.navigate(page, hipermaxi.BRANCH_URL, policy(), 0)

    def test_robots_requires_valid_rules(self):
        context = MagicMock()
        response = context.request.get.return_value
        response.status = 200
        response.text.return_value = "<html>Not robots</html>"
        with self.assertRaises(RuntimeError):
            hipermaxi.robots(context)
        response.text.return_value = "User-Agent: *\nAllow: /\nDisallow: /private/"
        with self.assertRaises(ValueError):
            hipermaxi.robots(context).check(hipermaxi.BASE_URL + "/private/")


class BrowserTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(hipermaxi, "pause")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_category_readiness_waits_for_delayed_navigation(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()
                url = hipermaxi.BRANCH_URL + "/categoria/farmacia-genericos"
                page.route("https://www.hipermaxi.com/**", lambda route: route.fulfill(
                    content_type="text/html", body=f"""
                        <main><p>Loading</p></main>
                        <script>setTimeout(() => {{
                            document.querySelector('main').innerHTML =
                                '<h1>Farmacia Genericos</h1><a href="{url}">Todo</a>';
                        }}, 100)</script>
                    """,
                ))
                page.goto(url + "/child")
                self.assertFalse(page.evaluate(hipermaxi.WAIT_FOR_CATEGORY, url))
                page.wait_for_function(hipermaxi.WAIT_FOR_CATEGORY, arg=url, timeout=2000)
                self.assertEqual(page.locator("main h1").inner_text(), "Farmacia Genericos")
                page.locator("main a").evaluate("(link) => link.href = '/another-category'")
                self.assertFalse(page.evaluate(hipermaxi.WAIT_FOR_CATEGORY, url))
            finally:
                browser.close()

    def test_loaded_main_category_does_not_click_hidden_todo(self):
        page = MagicMock()
        page.url = hipermaxi.BRANCH_URL + "/categoria/farmacia-genericos"
        with patch.object(hipermaxi, "navigate"):
            hipermaxi.open_all_products(page, page.url, policy(), 3)
        page.get_by_role.assert_not_called()
        calls = page.wait_for_function.call_args_list
        self.assertEqual(calls[0].args[0], hipermaxi.WAIT_FOR_CATEGORY)
        self.assertEqual(calls[0].kwargs, {"arg": page.url, "timeout": 60_000})
        self.assertEqual(calls[1].args[0], hipermaxi.WAIT_FOR_BATCH)
        self.assertEqual(calls[1].kwargs, {"arg": 0, "timeout": 60_000})

    def test_main_category_with_hidden_todo_and_products_is_ready(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()
                url = hipermaxi.BRANCH_URL + "/categoria/farmacia-genericos"
                page.route("https://www.hipermaxi.com/**", lambda route: route.fulfill(
                    content_type="text/html", body=f"""
                        <main><h1>Farmacia Genericos</h1>
                        <a style="display:none" href="{url}">Todo</a>
                        <article><h3>Example product</h3></article></main>
                    """,
                ))
                hipermaxi.open_all_products(page, url, policy(), 3)
                self.assertEqual(page.url, url)
                self.assertEqual(page.locator("main article").count(), 1)
                page.locator("article").evaluate("(node) => node.remove()")
                self.assertFalse(page.evaluate(hipermaxi.WAIT_FOR_CATEGORY, url))
                page.locator("main").evaluate(
                    "(node) => node.insertAdjacentHTML('beforeend', '<p>No hay productos</p>')",
                )
                self.assertTrue(page.evaluate(hipermaxi.WAIT_FOR_CATEGORY, url))
            finally:
                browser.close()

    def test_subcategory_selects_todo_before_collecting_products(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()
                url = hipermaxi.BRANCH_URL + "/categoria/farmacia-genericos"
                page.route("https://www.hipermaxi.com/**", lambda route: route.fulfill(
                    content_type="text/html", body=f"""
                        <main><h1>Farmacia Genericos</h1><a href="{url}">Todo</a>
                        <article><h3>Example product</h3></article></main>
                    """,
                ))
                original_navigate = hipermaxi.navigate

                def navigate_to_child(page, target, rules, delay, validation_timeout):
                    self.assertEqual(target, url)
                    original_navigate(page, target + "/child", rules, delay, validation_timeout)

                with patch.object(hipermaxi, "navigate", side_effect=navigate_to_child):
                    hipermaxi.open_all_products(page, url, policy(), 3)
                self.assertEqual(page.url, url)
                self.assertEqual(page.locator("main article").count(), 1)
            finally:
                browser.close()

    def test_changed_product_prefix_after_reload_fails(self):
        page = MagicMock()
        page.url = hipermaxi.BRANCH_URL + "/categoria/farmacia-genericos"
        changed = card() | {"href": hipermaxi.BRANCH_PATH + "/producto/456/changed"}
        page.locator.return_value.evaluate_all.side_effect = [[card()], [changed, card()]]
        page.locator.return_value.inner_text.return_value = "Loading"
        batches = []
        with patch.object(hipermaxi, "open_all_products"), self.assertRaisesRegex(
            ValueError, "previously collected products changed",
        ):
            hipermaxi.collect_category(
                page, {"name": "Genericos", "url": page.url}, policy(), 0, "test", batches.append,
            )
        self.assertEqual(len(batches), 1)

    def test_local_challenge_return_preserves_browser_session(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                context = browser.new_context()
                context.add_cookies([{
                    "name": "session_fixture", "value": "same-session", "url": hipermaxi.BASE_URL,
                }])
                page = context.new_page()
                context.route("https://www.hipermaxi.com/**", lambda route: route.fulfill(
                    content_type="text/html", body="<main>Catalog</main>",
                ))
                context.route("https://validate.perfdrive.com/**", lambda route: route.fulfill(
                    content_type="text/html",
                    body=f"""<script>setTimeout(() => {{
                        location.href = {json.dumps(hipermaxi.BRANCH_URL)};
                    }}, 500)</script>""",
                ))
                page.goto("https://validate.perfdrive.com/")
                with self.assertLogs(hipermaxi.LOGGER):
                    self.assertTrue(hipermaxi.wait_for_catalog(page, policy(), 5))
                self.assertEqual(page.url, hipermaxi.BRANCH_URL)
                self.assertEqual(page.locator("main").inner_text(), "Catalog")
                self.assertEqual(context.cookies(hipermaxi.BASE_URL)[0]["value"], "same-session")
                self.assertEqual(len(context.pages), 1)
            finally:
                browser.close()

    def test_collection_writes_only_new_cards_per_batch(self):
        page = MagicMock()
        page.url = hipermaxi.BRANCH_URL + "/categoria/farmacia-genericos"
        second = card() | {"href": hipermaxi.BRANCH_PATH + "/producto/456/second"}
        page.locator.return_value.evaluate_all.side_effect = [[card()], [card(), second]]
        page.locator.return_value.inner_text.side_effect = [
            "Products", "Has visto todos los productos de Farmacia Genéricos",
        ]
        batches = []
        with patch.object(hipermaxi, "open_all_products"):
            result = hipermaxi.collect_category(
                page, {"name": "Farmacia Genéricos", "url": page.url},
                policy(), 0, "test", batches.append,
            )
        self.assertEqual(result["observations"], 2)
        self.assertEqual(result["products"], 2)
        self.assertEqual([rows[0]["product_id"] for rows in batches], ["123", "456"])
        self.assertEqual([rows[0]["batch"] for rows in batches], ["1", "2"])
        page.wait_for_function.assert_called_once_with(hipermaxi.WAIT_FOR_BATCH, arg=1)
        page.locator.return_value.last.evaluate.assert_called_once()
        page.locator.return_value.last.scroll_into_view_if_needed.assert_not_called()

    def test_animated_scroll_sentinel_loads_next_batch_without_stability_wait(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": 800, "height": 400})
                page.set_default_timeout(1000)
                url = hipermaxi.BRANCH_URL + "/categoria/farmacia-quirurgicos"
                page.route("**/*", lambda route: route.fulfill(
                    content_type="text/html", body=f"""
                        <style>
                          @keyframes loading {{ from {{ transform: translateX(0); }}
                            to {{ transform: translateX(200px); }} }}
                          [role="status"] {{ width: 40px; height: 20px;
                            animation: loading 1s linear infinite alternate; }}
                        </style>
                        <main><h1>Farmacia Quirurgicos</h1>
                          <article>
                            <a href="{hipermaxi.BRANCH_PATH}/producto/123/example"><h3>First</h3></a>
                            <div aria-label="Precio del producto"><span>Bs 1.00</span></div>
                          </article>
                          <div style="height:2000px"></div>
                          <div role="status">Loading</div>
                        </main>
                        <script>
                          const sentinel = document.querySelector('[role="status"]');
                          const observer = new IntersectionObserver(entries => {{
                            if (!entries.some(entry => entry.isIntersecting)) return;
                            observer.disconnect();
                            document.querySelector('main').insertAdjacentHTML('beforeend', `
                              <article>
                                <a href="{hipermaxi.BRANCH_PATH}/producto/456/second"><h3>Second</h3></a>
                                <div aria-label="Precio del producto"><span>Bs 2.00</span></div>
                              </article><p>Has visto todos los productos</p>`);
                            sentinel.remove();
                          }});
                          observer.observe(sentinel);
                        </script>
                    """,
                ))
                page.goto(url)
                with self.assertRaises(PlaywrightTimeoutError):
                    page.locator('main [role="status"]').scroll_into_view_if_needed(timeout=300)
                rows = []
                result = hipermaxi.collect_category(
                    page, {"name": "Farmacia Quirurgicos", "url": url},
                    policy(), 0, "test", rows.extend,
                )
                self.assertEqual([row["product_id"] for row in rows], ["123", "456"])
                self.assertEqual([row["batch"] for row in rows], ["1", "2"])
                self.assertEqual(result["observations"], 2)
                self.assertTrue(result["terminal_marker"])
            finally:
                browser.close()

    def test_no_progress_times_out_not_success(self):
        page = MagicMock()
        page.url = hipermaxi.BRANCH_URL + "/categoria/farmacia-genericos"
        page.locator.return_value.evaluate_all.return_value = [card()]
        page.locator.return_value.inner_text.return_value = "Loading"
        page.wait_for_function.side_effect = PlaywrightTimeoutError("No new products")
        with patch.object(hipermaxi, "open_all_products"), self.assertRaises(PlaywrightTimeoutError):
            hipermaxi.collect_category(
                page, {"name": "Farmacia Genéricos", "url": page.url},
                policy(), 0, "test", lambda _rows: None,
            )

    def test_scroll_error_stops_collection_without_replaying_writes(self):
        page = MagicMock()
        page.url = hipermaxi.BRANCH_URL + "/categoria/farmacia-genericos"
        page.locator.return_value.evaluate_all.return_value = [card()]
        page.locator.return_value.inner_text.return_value = "Loading"
        page.locator.return_value.last.evaluate.side_effect = hipermaxi.PlaywrightError("Page closed")
        batches = []
        with patch.object(hipermaxi, "open_all_products"), self.assertRaisesRegex(
            hipermaxi.PlaywrightError, "Page closed",
        ):
            hipermaxi.collect_category(
                page, {"name": "Farmacia Genericos", "url": page.url},
                policy(), 0, "test", batches.append,
            )
        self.assertEqual(len(batches), 1)
        page.wait_for_function.assert_not_called()

    def test_cards_discovery_and_infinite_scroll_terminal_marker(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()
                page.set_content(f"""
                  <nav aria-label="Menú principal de categorías">
                    <a href="{hipermaxi.BRANCH_PATH}/categoria/farmacia-genericos">Farmacia Genéricos</a>
                  </nav>
                  <main><article>
                    <a href="{hipermaxi.BRANCH_PATH}/producto/123/example"><h3>Example</h3></a>
                    <img src="/image.jpg"><span>-25% OFF</span>
                    <div aria-label="Precio del producto"><span>Bs 396.90</span><span>Bs 529.30</span></div>
                  </article><div role="status"></div></main>
                """)
                entries = hipermaxi.discover_categories(page)
                self.assertEqual(entries[0]["name"], "Farmacia Genéricos")
                cards = page.locator("main article").evaluate_all(hipermaxi.EXTRACT_CARDS)
                self.assertEqual(cards[0]["current_price_text"], "Bs 396.90")
                self.assertEqual(cards[0]["regular_price_text"], "Bs 529.30")
                self.assertEqual(cards[0]["discount_label"], "-25% OFF")
                page.evaluate("""() => setTimeout(() => {
                    document.querySelector('main').insertAdjacentHTML(
                      'beforeend', '<article><h3>Second</h3></article><p>Has visto todos los productos</p>');
                }, 50)""")
                page.wait_for_function(hipermaxi.WAIT_FOR_BATCH, arg=1)
                self.assertEqual(page.locator("main article").count(), 2)
            finally:
                browser.close()

    def test_explicit_terminal_marker_completes_category(self):
        page = MagicMock()
        page.url = hipermaxi.BRANCH_URL + "/categoria/farmacia-genericos"
        page.locator.return_value.evaluate_all.return_value = [card()]
        page.locator.return_value.inner_text.return_value = "Has visto todos los productos de Farmacia Genéricos"
        rows = []
        with patch.object(hipermaxi, "open_all_products"):
            result = hipermaxi.collect_category(
                page, {"name": "Farmacia Genéricos", "url": page.url},
                policy(), 0, "test", rows.extend,
            )
        self.assertEqual(result["observations"], 1)
        self.assertTrue(result["terminal_marker"])
        self.assertEqual(rows[0]["category"], "Farmacia Genéricos")

    def test_missing_sentinel_fails_instead_of_truncating(self):
        page = MagicMock()
        page.url = hipermaxi.BRANCH_URL + "/categoria/farmacia-genericos"
        page.locator.return_value.evaluate_all.return_value = [card()]
        page.locator.return_value.inner_text.return_value = "Loading"
        page.locator.return_value.last.count.return_value = 0
        with patch.object(hipermaxi, "open_all_products"), self.assertRaisesRegex(ValueError, "Missing scroll"):
            hipermaxi.collect_category(
                page, {"name": "Farmacia Genéricos", "url": page.url},
                policy(), 0, "test", lambda _rows: None,
            )


class PacingTests(unittest.TestCase):
    def test_three_second_floor_and_random_extra_delay(self):
        for delay, extra, expected in [(0, 0, 3), (3, 2, 5), (10, 1.5, 11.5)]:
            with self.subTest(delay=delay, extra=extra), patch.object(
                hipermaxi.random, "uniform", return_value=extra,
            ) as uniform, patch.object(hipermaxi.time, "sleep") as sleep:
                hipermaxi.pause(delay)
                uniform.assert_called_once_with(0, 2)
                sleep.assert_called_once_with(expected)

    def test_invalid_delays_fail(self):
        for delay in [-1, float("nan"), float("inf")]:
            with self.subTest(delay=delay), self.assertRaises(ValueError):
                hipermaxi.pause(delay)


class OutputTests(unittest.TestCase):
    def test_non_timeout_category_failure_is_not_retried(self):
        entry = {"name": "Alimentos", "url": hipermaxi.BRANCH_URL + "/categoria/alimentos"}
        with TemporaryDirectory() as output, patch.object(
            hipermaxi, "sync_playwright",
        ), patch.object(hipermaxi, "robots", return_value=policy()), patch.object(
            hipermaxi, "navigate",
        ), patch.object(hipermaxi, "catalog_action", return_value=[entry]), patch.object(
            hipermaxi, "collect_category", side_effect=ValueError("Invalid product"),
        ) as collect, patch.object(hipermaxi, "pause") as pause:
            with self.assertRaisesRegex(ValueError, "Invalid product"):
                hipermaxi.run(Path(output), None, 3)
            collect.assert_called_once()
            pause.assert_not_called()
            summary = json.loads(next(Path(output).glob("*/summary.json")).read_text())
            self.assertEqual(summary["category_attempts"][0]["status"], "failed")
            self.assertEqual(summary["status"], "failed")

    def test_category_timeout_retries_retain_rows_and_record_attempts(self):
        entry = {"name": "Alimentos", "url": hipermaxi.BRANCH_URL + "/categoria/alimentos"}
        for failures in (1, 2, 3):
            calls = []

            def collect(page, category, robots, delay, run_id, write, timeout):
                calls.append(category)
                write([hipermaxi.observation(card(), "Alimentos", entry["url"], 1, run_id, "test")])
                if len(calls) <= failures:
                    raise PlaywrightTimeoutError("Batch stalled")
                return {"warnings": [], "observations": 1}

            with self.subTest(failures=failures), TemporaryDirectory() as output, patch.object(
                hipermaxi, "sync_playwright",
            ), patch.object(hipermaxi, "robots", return_value=policy()), patch.object(
                hipermaxi, "navigate",
            ), patch.object(hipermaxi, "catalog_action", return_value=[entry]), patch.object(
                hipermaxi, "collect_category", side_effect=collect,
            ), patch("pipelines.ingestion.bronze.category_retries.time.sleep") as pause:
                if failures == 3:
                    with self.assertRaises(PlaywrightTimeoutError):
                        hipermaxi.run(Path(output), None, 3)
                else:
                    hipermaxi.run(Path(output), None, 3)
                summary = json.loads(next(Path(output).glob("*/summary.json")).read_text())
                expected_attempts = min(failures + 1, 3)
                self.assertEqual(len(calls), expected_attempts)
                self.assertEqual(summary["observations"], expected_attempts)
                self.assertEqual(len(summary["category_attempts"]), expected_attempts)
                self.assertEqual(
                    summary["status"], "failed" if failures == 3 else "completed_with_warnings",
                )
                self.assertEqual(pause.call_count, min(failures, 2))
                self.assertTrue(all(a["observations"] == 1 for a in summary["category_attempts"]))

    def test_explicit_exclusion_preserves_other_categories(self):
        entries = [
            {"name": "No Comestible", "url": hipermaxi.BRANCH_URL + "/categoria/no-comestible"},
            {"name": "Genericos", "url": hipermaxi.BRANCH_URL + "/categoria/genericos"},
        ]
        for excluded, error in [
            (["no-comestible"], None),
            (["unknown"], "Unknown excluded"),
            (["no-comestible", "genericos"], "No categories remain"),
        ]:
            with self.subTest(excluded=excluded), TemporaryDirectory() as output, patch.object(
                hipermaxi, "sync_playwright",
            ), patch.object(hipermaxi, "robots", return_value=policy()), patch.object(
                hipermaxi, "navigate",
            ), patch.object(hipermaxi, "catalog_action", return_value=entries), patch.object(
                hipermaxi, "collect_category", return_value={"warnings": []},
            ) as collect:
                if error:
                    with self.assertRaisesRegex(ValueError, error):
                        hipermaxi.run(Path(output), None, 0, excluded_categories=excluded)
                    collect.assert_not_called()
                else:
                    directory = hipermaxi.run(Path(output), None, 0, excluded_categories=excluded)
                    collect.assert_called_once()
                    self.assertEqual(collect.call_args.args[1], entries[1])
                    summary = json.loads((directory / "summary.json").read_text())
                    self.assertEqual(summary["excluded_categories"], excluded)
                    self.assertEqual(summary["requested_categories"], [entries[1]])

    def test_interactive_launch_and_manual_timeout_wired_into_run(self):
        for interactive in (False, True):
            with self.subTest(interactive=interactive), TemporaryDirectory() as output, patch.object(
                hipermaxi, "sync_playwright",
            ) as playwright, patch.object(hipermaxi, "robots", return_value=policy()), patch.object(
                hipermaxi, "navigate",
            ) as navigate, patch.object(hipermaxi, "catalog_action", return_value=[
                {"name": "Genericos", "url": hipermaxi.BRANCH_URL + "/categoria/genericos"},
            ]), patch.object(
                hipermaxi, "collect_category", return_value={"warnings": []},
            ) as collect:
                directory = hipermaxi.run(Path(output), None, 0, interactive=interactive, validation_timeout=42)
                playwright.return_value.__enter__.return_value.chromium.launch.assert_called_once_with(
                    headless=not interactive,
                )
                playwright.return_value.__enter__.return_value.chromium.launch.return_value.new_context.assert_called_once_with(
                    locale="es-BO", timezone_id="America/La_Paz",
                )
                self.assertEqual(navigate.call_args.args[-1], 42 if interactive else 0)
                self.assertEqual(collect.call_args.args[-1], 42 if interactive else 0)
                summary = json.loads((directory / "summary.json").read_text())
                self.assertEqual(summary["retailer"], "hipermaxi")
                self.assertEqual(summary["status"], "completed")
                self.assertEqual(summary["interactive"], interactive)
                self.assertEqual(summary["validation_timeout_seconds"], 42 if interactive else 0)
                context = playwright.return_value.__enter__.return_value.chromium.launch.return_value.new_context.return_value
                route_handler = context.route.call_args.args[1]
                page = context.new_page.return_value
                page.url = "https://validate.perfdrive.com/"
                route = MagicMock()
                route.request.resource_type = "document"
                route.request.is_navigation_request.return_value = True
                route.request.url = page.url
                if interactive:
                    route_handler(route)
                    route.continue_.assert_called_once()
                    route.abort.assert_not_called()
                else:
                    with self.assertLogs(hipermaxi.LOGGER):
                        route_handler(route)
                    route.abort.assert_called_once()
                route = MagicMock()
                route.request.resource_type = "image"
                route.request.is_navigation_request.return_value = False
                route_handler(route)
                if interactive:
                    route.continue_.assert_called_once()
                else:
                    route.abort.assert_called_once()
                route = MagicMock()
                route.request.resource_type = "document"
                route.request.is_navigation_request.return_value = True
                route.request.url = "https://newassets.hcaptcha.com/captcha/frame.html"
                route.request.frame = MagicMock()
                if interactive:
                    route_handler(route)
                    route.continue_.assert_called_once()
                    route.abort.assert_not_called()
                    route.request.frame = page.main_frame
                    route.reset_mock()
                    with self.assertLogs(hipermaxi.LOGGER):
                        route_handler(route)
                    route.abort.assert_called_once()
                else:
                    with self.assertLogs(hipermaxi.LOGGER):
                        route_handler(route)
                    route.abort.assert_called_once()

    def test_invalid_manual_timeouts_rejected_before_output(self):
        with TemporaryDirectory() as output:
            for timeout in [0, -1, float("nan"), float("inf")]:
                with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                    hipermaxi.run(Path(output), None, 0, interactive=True, validation_timeout=timeout)
            self.assertEqual(list(Path(output).iterdir()), [])

    def test_formats_preserve_categories_and_nulls(self):
        row = hipermaxi.observation(
            card(), "Genericos", hipermaxi.BRANCH_URL + "/categoria/genericos",
            1, "test", "2026-10-30T16:00:00+00:00",
        )
        with TemporaryDirectory() as output:
            snapshot = SnapshotWriter(Path(output), "scrape_hipermaxi_20261030T170000Z", hipermaxi.FIELDS)
            with snapshot:
                snapshot.write([row])
            self.assertEqual(pq.read_table(Path(output) / snapshot.files["parquet"]).to_pylist(), [row])
            self.assertEqual(json.loads((Path(output) / snapshot.files["jsonl"]).read_text()), row)
            with (Path(output) / snapshot.files["csv"]).open() as stream:
                self.assertEqual(next(csv.DictReader(stream))["category"], "Genericos")

    def test_blocked_run_marks_failed_and_closes_browser(self):
        with TemporaryDirectory() as output, patch.object(
            hipermaxi, "sync_playwright",
        ) as playwright, patch.object(hipermaxi, "robots", return_value=policy()), patch.object(
            hipermaxi, "navigate", side_effect=RuntimeError("Bot validation"),
        ):
            with self.assertRaisesRegex(RuntimeError, "Bot validation"):
                hipermaxi.run(Path(output), None, 0)
            summary = json.loads(next(Path(output).glob("*/summary.json")).read_text())
            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["observations"], 0)
            playwright.return_value.__enter__.return_value.chromium.launch.return_value.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
