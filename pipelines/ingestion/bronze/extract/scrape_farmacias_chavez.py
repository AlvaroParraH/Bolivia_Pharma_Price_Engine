"""Collect public Chavez category cards using a single headless Chromium page."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from uuid import uuid4

from playwright.sync_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from pipelines.ingestion.bronze.extract.category_retries import collect_with_retries
from pipelines.ingestion.bronze.extract.snapshot import SnapshotWriter


BASE_URL = "https://www.farmaciaschavez.com.bo"
USER_AGENT = "BoliviaPharmaPriceEngine/0.1"
LOGGER = logging.getLogger(__name__)
FIELDS = [
    "run_id", "observed_at", "retailer", "category", "category_url", "page_url",
    "product_url", "product_id", "name", "display_name", "currency", "price",
    "discount_price", "current_price", "discount_percent", "discount_label",
    "availability_label", "image_url", "current_price_text", "regular_price_text",
    "market_context",
]
EXTRACT_CARDS = """cards => cards.map(card => {
    const text = selector => card.querySelector(selector)?.textContent.trim() || null;
    return {
        href: card.getAttribute('href'),
        name: card.querySelector('img')?.getAttribute('alt') || null,
        display_name: text('[data-testid="card-name"]'),
        current_price_text: text('[data-testid="crossed-out-current"]')
            || text('.base__price'),
        regular_price_text: text('[data-testid="crossed-out-old"]'),
        discount_label: text('button[class*="PromoTag"]'),
        image_url: card.querySelector('img')?.getAttribute('src') || null,
        availability_label: /agotado|sin stock|no disponible/i.test(card.innerText)
            ? card.innerText.match(/agotado|sin stock|no disponible/i)[0] : null
    };
})"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_price(text: str) -> Decimal:
    match = re.fullmatch(
        r"\s*\(?Bs\.?\s*(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{1,2}))?\)?\s*", text,
    )
    if match is None:
        raise ValueError(f"Unrecognized Chavez BOB price: {text!r}")
    return Decimal(match[1].replace(".", "") + "." + (match[2] or "0"))


def public_url(url: str, kind: str) -> str:
    absolute = urljoin(BASE_URL, url)
    parts = urlsplit(absolute)
    pattern = r"/ca/[^/]+/\d+" if kind == "category" else r"/p/[^/]+-\d+"
    if parts.scheme != "https" or parts.netloc != urlsplit(BASE_URL).netloc or not re.fullmatch(pattern, parts.path):
        raise ValueError(f"Unexpected Chavez {kind} URL: {url}")
    if parts.query or parts.fragment:
        raise ValueError(f"Unexpected query/fragment in {kind} URL: {url}")
    return absolute


def observation(
    card: dict[str, str | None], category: str, category_url: str,
    page_url: str, run_id: str, timestamp: str,
) -> dict[str, str | None]:
    if not card["href"] or not card["name"] or not card["display_name"] or not card["current_price_text"]:
        raise ValueError(f"Missing product name, link or price: {card!r}")
    url = public_url(card["href"], "product")
    current = parse_price(card["current_price_text"])
    regular = parse_price(card["regular_price_text"]) if card["regular_price_text"] else current
    if regular < current:
        raise ValueError(f"Regular price below current price: {url}")
    discounted = regular > current
    return {
        "run_id": run_id, "observed_at": timestamp, "retailer": "farmacias_chavez",
        "category": category, "category_url": category_url, "page_url": page_url,
        "product_url": url, "product_id": url.rsplit("-", 1)[1],
        "name": card["name"], "display_name": card["display_name"], "currency": "BOB",
        "price": f"{regular:.2f}", "discount_price": f"{current:.2f}" if discounted else None,
        "current_price": f"{current:.2f}",
        "discount_percent": f"{(regular-current)/regular*100:.2f}" if discounted else None,
        "discount_label": card["discount_label"], "availability_label": card["availability_label"],
        "image_url": card["image_url"], "current_price_text": card["current_price_text"],
        "regular_price_text": card["regular_price_text"],
        "market_context": "public_web_no_location_selected",
    }


def check_robots(context: BrowserContext) -> tuple[RobotFileParser, list[str]]:
    response = context.request.get(BASE_URL + "/robots.txt")
    text = response.text()
    warnings = []
    if response.status in {404, 410} or (
        response.status == 200 and (
            "text/html" in response.headers.get("content-type", "")
            or "<html" in text.lower() or "<!doctype" in text.lower()
        )
    ):
        warnings.append("No usable robots.txt; proceeding with public-page collection")
        LOGGER.warning("%s", warnings[-1])
        text = "User-agent: *\nAllow: /"
    elif response.status != 200:
        raise RuntimeError(f"Cannot verify robots.txt: HTTP {response.status}")
    policy = RobotFileParser()
    policy.parse(text.splitlines())
    return policy, warnings


def navigate(page: Page, url: str, policy: RobotFileParser, delay: float) -> None:
    if not policy.can_fetch(USER_AGENT, url):
        raise ValueError(f"robots.txt disallows {url}")
    time.sleep(delay)
    response = page.goto(url, wait_until="domcontentloaded")
    if response is None or response.status >= 400:
        raise RuntimeError(f"Navigation failed for {url}: {response.status if response else 'no response'}")
    if page.url != url:
        raise RuntimeError(f"Unexpected redirect from {url} to {page.url}")


def open_menu(page: Page) -> None:
    menu = page.locator(".category-tree-modal").first
    if not menu.is_visible():
        page.get_by_test_id("header-categories-button").click()
    menu.wait_for(state="visible")


def discover_names(page: Page) -> list[str]:
    open_menu(page)
    names = page.locator(".category-tree-modal").first.locator(
        ":scope > li.category-level-1 button",
    ).all_text_contents()
    names = list(dict.fromkeys(name.strip() for name in names))
    if not names or any(not name for name in names):
        raise ValueError("No main categories found in Chavez menu")
    return names


def open_category(page: Page, name: str, delay: float) -> str:
    open_menu(page)
    time.sleep(delay)
    button = page.locator(".category-tree-modal").first.get_by_role(
        "button", name=name, exact=True,
    )
    button.focus()
    button.press("Enter")
    page.wait_for_url(re.compile(re.escape(BASE_URL) + r"/ca/[^/]+/\d+$"))
    page.locator("h1").filter(has_text=name).wait_for()
    return public_url(page.url, "category")


def read_page(page: Page) -> tuple[int, list[dict[str, str | None]], int, int]:
    heading = page.locator("h1")
    heading.wait_for()
    count_text = heading.locator("..").locator("p").inner_text().strip()
    if not re.fullmatch(r"\([\d.,]+\)", count_text):
        raise ValueError(f"Cannot verify product count: {count_text!r}")
    total = int(re.sub(r"\D", "", count_text))
    if total:
        page.locator("a.containerCard .base__price").first.wait_for()
    cards = page.locator("a.containerCard").evaluate_all(EXTRACT_CARDS)
    pager = page.locator(".ant-pagination-simple-pager")
    if pager.count():
        title = pager.get_attribute("title") or ""
        match = re.fullmatch(r"(\d+)/(\d+)", title)
        if not match:
            raise ValueError(f"Unrecognized pagination: {title!r}")
        current, last = int(match[1]), int(match[2])
    else:
        current, last = 1, 1
        if len(cards) < total:
            raise ValueError("Missing pagination despite more advertised products")
    return total, cards, current, last


def wait_for_page_change(
    page: Page, url: str, number: int, previous: tuple[str | None, ...],
) -> None:
    page.wait_for_url(url, wait_until="domcontentloaded")
    page.wait_for_function(
        """expected => {
            const pager = document.querySelector('.ant-pagination-simple-pager');
            const current = Number(pager?.getAttribute('title')?.split('/')[0]);
            const cards = [...document.querySelectorAll('a.containerCard')];
            const ids = cards.map(n => n.getAttribute('href'));
            return current === expected.number && ids.length
                && cards.every(n => n.querySelector('.base__price'))
                && JSON.stringify(ids) !== JSON.stringify(expected.previous);
        }""", arg={"number": number, "previous": list(previous)},
    )


def collect_category(
    page: Page, name: str, policy: RobotFileParser, delay: float, run_id: str,
    write: Callable[[list[dict[str, str | None]]], None],
) -> dict[str, object]:
    url = open_category(page, name, delay)
    if not policy.can_fetch(USER_AGENT, url):
        raise ValueError(f"robots.txt disallows {url}")
    seen: set[str] = set()
    totals: list[int] = []
    warnings: list[str] = []
    pages: list[dict[str, object]] = []
    previous_fingerprint: tuple[str | None, ...] | None = None
    page_number = 1
    while True:
        total, cards, current, last = read_page(page)
        if current != page_number or current > last:
            raise ValueError(f"Unexpected page {current}, expected {page_number}")
        if total and not cards:
            raise ValueError(f"No products on {page.url}")
        fingerprint = tuple(card["href"] for card in cards)
        if previous_fingerprint is not None and fingerprint == previous_fingerprint:
            raise ValueError(f"Repeated full page at {page.url}")
        if total not in totals:
            if totals:
                warnings.append(f"Advertised total changed from {totals} to {total}")
            totals.append(total)
        timestamp = utc_now()
        rows = [observation(card, name, url, page.url, run_id, timestamp) for card in cards]
        identifiers = [row["product_url"] for row in rows]
        if seen.intersection(identifiers) or len(set(identifiers)) != len(identifiers):
            warnings.append(f"Repeated products retained on page {current}")
        seen.update(identifier for identifier in identifiers if identifier is not None)
        write(rows)
        pages.append({"page": current, "url": page.url, "observations": len(rows), "reported_total": total})
        LOGGER.info("%s: page %d/%d; %d unique / %d advertised", name, current, last, len(seen), total)
        if current == last:
            if not page.locator(".ant-pagination-next").count() or page.locator(".ant-pagination-next").get_attribute("aria-disabled") == "true":
                break
            raise ValueError("Last page has an enabled next button")
        next_button = page.locator(".ant-pagination-next button")
        if not next_button.is_enabled():
            raise ValueError("Next page disabled before advertised last page")
        next_url = f"{url}?currentPage={current+1}"
        if not policy.can_fetch(USER_AGENT, next_url):
            raise ValueError(f"robots.txt disallows {next_url}")
        time.sleep(delay)
        try:
            next_button.click()
            wait_for_page_change(page, next_url, current + 1, fingerprint)
        except PlaywrightTimeoutError:
            warning = f"Pagination timed out at page {current + 1}; reloading that page once"
            warnings.append(warning)
            LOGGER.warning("%s: %s", name, warning)
            navigate(page, next_url, policy, delay)
            wait_for_page_change(page, next_url, current + 1, fingerprint)
        previous_fingerprint = fingerprint
        page_number += 1
    if len(seen) != totals[-1]:
        warnings.append(f"Last advertised total {totals[-1]}; {len(seen)} unique products collected")
    for warning in warnings:
        LOGGER.warning("%s: %s", name, warning)
    return {"name": name, "url": url, "pages": len(pages), "page_results": pages,
            "products": len(seen), "observations": sum(int(p["observations"]) for p in pages),
            "reported_totals": totals, "warnings": warnings}


def run(output: Path, categories: list[str] | None, delay: float) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = timestamp + "_" + uuid4().hex[:8]
    directory = output / run_id
    directory.mkdir(parents=True, exist_ok=False)
    snapshot = SnapshotWriter(directory, f"scrape_farmacias_chavez_{timestamp}", FIELDS)
    manifest: dict[str, object] = {
        "retailer": "farmacias_chavez",
        "run_id": run_id, "started_at": utc_now(), "status": "running",
        "observations": 0, "categories": [], "output_files": snapshot.files,
        "warnings": [], "requested_categories": categories or [],
        "category_timeout_retries": 2,
    }
    attempts: list[dict[str, object]] = []
    manifest["category_attempts"] = attempts
    count = 0
    completed: list[dict[str, object]] = []

    def save() -> None:
        temporary = directory / "summary.tmp"
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(directory / "summary.json")

    def write(rows: list[dict[str, str | None]]) -> None:
        nonlocal count
        snapshot.write(rows)
        count += len(rows)
        manifest["observations"] = count
        if rows:
            manifest["active_category"] = rows[0]["category"]
            manifest["active_page_url"] = rows[0]["page_url"]
        save()

    save()
    try:
        with snapshot, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(locale="es-BO", timezone_id="America/La_Paz")
                context.set_default_timeout(30_000)
                context.set_default_navigation_timeout(60_000)
                context.route("**/*", lambda route: route.abort() if route.request.resource_type in
                              {"image", "media", "font"} else route.continue_())
                policy, warnings = check_robots(context)
                manifest["warnings"] = warnings
                context.route(
                    "**/*",
                    lambda route: route.abort() if (
                        route.request.resource_type in {"image", "media", "font"}
                        or (route.request.is_navigation_request() and (
                            urlsplit(route.request.url).netloc != urlsplit(BASE_URL).netloc
                            or not policy.can_fetch(USER_AGENT, route.request.url)
                        ))
                    ) else route.continue_(),
                )
                page = context.new_page()
                navigate(page, BASE_URL + "/", policy, delay)
                names = discover_names(page)
                if categories and any(name not in names for name in categories):
                    raise ValueError(f"Unknown category; available names: {names}")
                names = list(dict.fromkeys(categories or names))
                manifest["requested_categories"] = names
                save()
                for name in names:
                    def collect_attempt(attempt_number: int) -> dict[str, object]:
                        if attempt_number > 1:
                            navigate(page, BASE_URL + "/", policy, delay)
                        return collect_category(page, name, policy, delay, run_id, write)

                    completed.append(collect_with_retries(
                        collect_attempt, category={"name": name}, attempts=attempts,
                        observations=lambda: count, save=save, delay=delay, logger=LOGGER,
                    ))
                    manifest["categories"] = completed
                    save()
            finally:
                browser.close()
        manifest["active_category"] = None
        manifest["active_page_url"] = None
        manifest["status"] = "completed_with_warnings" if manifest["warnings"] or any(
            item["warnings"] for item in completed
        ) or any(attempt["status"] == "timed_out" for attempt in attempts) else "completed"
    except BaseException as error:
        manifest["status"] = "failed"
        manifest["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        manifest["finished_at"] = utc_now()
        save()
        LOGGER.info("Snapshot %s: %s (%d observations)", directory, manifest["status"], count)
    return directory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", action="append", help="Exact main menu name; repeat, defaults to all main categories")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[4] / "data" / "farmacias_chavez")
    parser.add_argument("--delay", type=float, default=3)
    args = parser.parse_args()
    if not 3 <= args.delay < float("inf"):
        parser.error("--delay must be finite and at least three seconds")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(args.output, args.category, args.delay)


if __name__ == "__main__":
    main()
