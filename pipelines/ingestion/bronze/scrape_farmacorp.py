"""Scrape public Farmacorp category cards without visiting transactional pages."""

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
from typing import TypedDict
from urllib.parse import parse_qs, urljoin, urlsplit
from uuid import uuid4

from playwright.sync_api import BrowserContext, Page, sync_playwright

from pipelines.ingestion.bronze.snapshot import SnapshotWriter

BASE_URL = "https://farmacorp.com"
USER_AGENT = "BoliviaPharmaPriceEngine/0.1"
LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Card(TypedDict):
    name: str
    href: str
    brand: str | None
    current_price_text: str
    regular_price_text: str | None
    discount_label: str | None
    availability_label: str | None
    image_url: str | None


class Observation(TypedDict):
    run_id: str
    observed_at: str
    retailer: str
    category: str
    category_url: str
    page_url: str
    product_url: str
    product_handle: str
    name: str
    brand: str | None
    currency: str
    price: str
    discount_price: str | None
    current_price: str
    discount_percent: str | None
    discount_label: str | None
    availability_label: str | None
    image_url: str | None
    current_price_text: str
    regular_price_text: str | None
    market_context: str


EXTRACT_CARDS = """cards => cards.map(card => {
    const text = selector => card.querySelector(selector)?.textContent.trim() || null;
    return {
        name: text('.productitem--title a'),
        href: card.querySelector('.productitem--title a')?.getAttribute('href'),
        brand: text('.productitem--vendor'),
        current_price_text: text('.price--main .money'),
        regular_price_text: text('.price--compare-at .money'),
        discount_label: text('.badge--sale'),
        availability_label: text('.badge--soldout'),
        image_url: card.querySelector('img')?.getAttribute('src') || null
    };
})"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_price(text: str) -> Decimal:
    """Parse displayed Bolivian prices, never Shopify's ambiguous JSON-LD cents."""
    match = re.fullmatch(
        r"\s*(?:(?:Antes|Ahora)\s+)?Bs\.?\s*(\d{1,3}(?:\.\d{3})*|\d+),(\d{2})\s*",
        text,
    )
    if match is None:
        raise ValueError(f"Unrecognized BOB price: {text!r}")
    return Decimal(f"{match[1].replace('.', '')}.{match[2]}")


def collection_url(url: str) -> str:
    absolute = urljoin(BASE_URL, url)
    parts = urlsplit(absolute)
    if (
        parts.scheme != "https"
        or parts.netloc != "farmacorp.com"
        or not re.fullmatch(r"/collections/[a-zA-Z0-9_-]+", parts.path)
        or parts.fragment
    ):
        raise ValueError(f"Not a public Farmacorp collection URL: {url}")
    query = parse_qs(parts.query, keep_blank_values=True)
    if any(key not in {"page", "grid_list"} for key in query):
        raise ValueError(f"Refusing filtered/sorted collection URL: {url}")
    if "page" in query and (
        len(query["page"]) != 1
        or not query["page"][0].isdigit()
        or int(query["page"][0]) < 1
    ):
        raise ValueError(f"Invalid page number: {url}")
    if "grid_list" in query and query["grid_list"] not in (["grid-view"], [""]):
        raise ValueError(f"Unexpected grid mode: {url}")
    return absolute


class RobotsPolicy:
    """Match robots wildcard paths, with the most specific rule taking priority."""

    def __init__(self, text: str) -> None:
        groups: list[tuple[list[str], list[tuple[str, str]]]] = []
        agents: list[str] = []
        rules: list[tuple[str, str]] = []
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if rules:
                    groups.append((agents, rules))
                    agents, rules = [], []
                agents.append(value.lower())
            elif key in {"allow", "disallow"} and agents and value:
                rules.append((key, value))
        groups.append((agents, rules))
        specific = [
            group for group in groups
            if any(agent != "*" and USER_AGENT.lower().startswith(agent) for agent in group[0])
        ]
        selected = specific or [group for group in groups if "*" in group[0]]
        self.rules = [rule for _, group_rules in selected for rule in group_rules]

    def check(self, url: str) -> None:
        parts = urlsplit(url)
        path = parts.path + ("?" + parts.query if parts.query else "")
        matches: list[tuple[int, bool]] = []
        for kind, pattern in self.rules:
            end = pattern.endswith("$")
            source = pattern[:-1] if end else pattern
            regex = "^" + re.escape(source).replace(r"\*", ".*") + ("$" if end else "")
            if re.search(regex, path):
                matches.append((len(source.replace("*", "")), kind == "allow"))
        if matches and not max(matches)[1]:
            raise ValueError(f"robots.txt disallows {url}")


def observation(
    card: Card, *, category: str, page_url: str, run_id: str, observed_at: str,
) -> Observation:
    if not card["name"] or not card["href"] or not card["current_price_text"]:
        raise ValueError(f"Product card is missing a name, link or price: {card!r}")
    parts = urlsplit(urljoin(BASE_URL, card["href"]))
    match = re.fullmatch(r"(?:/collections/[^/]+)?/products/([^/]+)", parts.path)
    if parts.netloc != "farmacorp.com" or parts.scheme != "https" or match is None:
        raise ValueError(f"Unexpected product URL: {card['href']}")
    current = parse_price(card["current_price_text"])
    regular = parse_price(card["regular_price_text"]) if card["regular_price_text"] else current
    if regular < current:
        raise ValueError(f"Regular price is below current price for {card['name']}")
    discounted = regular > current
    if card["discount_label"] and card["discount_label"].casefold() != "venta" and not discounted:
        raise ValueError(f"Discount label without a lower price for {card['name']}")
    return {
        "run_id": run_id,
        "observed_at": observed_at,
        "retailer": "farmacorp",
        "category": category,
        "category_url": BASE_URL + urlsplit(page_url).path,
        "page_url": page_url,
        "product_url": f"{BASE_URL}/products/{match[1]}",
        "product_handle": match[1],
        "name": " ".join(card["name"].split()),
        "brand": card["brand"],
        "currency": "BOB",
        "price": f"{regular:.2f}",
        "discount_price": f"{current:.2f}" if discounted else None,
        "current_price": f"{current:.2f}",
        "discount_percent": (
            f"{(regular - current) / regular * 100:.2f}" if discounted else None
        ),
        "discount_label": card["discount_label"],
        "availability_label": card["availability_label"],
        "image_url": urljoin(BASE_URL, card["image_url"]) if card["image_url"] else None,
        "current_price_text": card["current_price_text"],
        "regular_price_text": card["regular_price_text"],
        "market_context": "public_web_no_branch_selected",
    }


def read_category(page: Page) -> tuple[str, int, list[Card], str | None]:
    heading = " ".join(page.locator("h1").inner_text().split())
    match = re.fullmatch(r"(.+?)\s*\(([\d.,]+)\s+productos?\)", heading, re.IGNORECASE)
    if match is None:
        raise ValueError(f"Cannot verify category product count from heading: {heading!r}")
    total = int(match[2].replace(".", "").replace(",", ""))
    if total:
        page.locator(".productgrid--item .price--main .money").first.wait_for()
    cards: list[Card] = page.locator(".productgrid--item").evaluate_all(EXTRACT_CARDS)
    if total and not cards:
        raise ValueError(f"No product cards on {page.url}, despite advertised count {total}")
    next_links = page.locator(".pagination--next a")
    if next_links.count() > 1:
        raise ValueError("Multiple next-page links found")
    next_url = next_links.get_attribute("href") if next_links.count() else None
    return match[1].strip(), total, cards, next_url


def navigate(page: Page, url: str, policy: RobotsPolicy, delay: float) -> None:
    policy.check(url)
    time.sleep(delay)
    response = page.goto(url, wait_until="domcontentloaded")
    if response is None or response.status >= 400:
        raise RuntimeError(f"Navigation failed for {url}: {response.status if response else 'no response'}")
    actual = collection_url(page.url)
    if urlsplit(actual).path != urlsplit(url).path or (
        parse_qs(urlsplit(actual).query).get("page", ["1"])
        != parse_qs(urlsplit(url).query).get("page", ["1"])
    ):
        raise RuntimeError(f"Unexpected redirect from {url} to {actual}")


def discover_categories(page: Page, *, main_only: bool = False) -> list[str]:
    urls: list[str] = []
    selector = (
        "#CategoriesNavPanel .navmenu-depth-1 > li > a[href]"
        if main_only else "#CategoriesNavPanel a[href]"
    )
    for href in page.locator(selector).evaluate_all(
        "links => links.map(link => link.getAttribute('href'))",
    ):
        if href.startswith("/collections/"):
            url = collection_url(href)
            if url not in urls:
                urls.append(url)
    if not urls:
        raise ValueError("No collection links found in the Categorias menu")
    return urls


def collect_category(
    page: Page, url: str, policy: RobotsPolicy, delay: float,
    run_id: str, write_rows: Callable[[list[Observation]], None],
) -> dict[str, object]:
    initial_path = urlsplit(url).path
    visited: set[str] = set()
    seen: set[str] = set()
    expected: int | None = None
    category_name = ""
    reported_totals: list[int] = []
    page_results: list[dict[str, object]] = []
    warnings: list[str] = []
    observation_count = 0

    def warn(message: str) -> None:
        warnings.append(message)
        LOGGER.warning("%s", message)

    while url:
        if url in visited:
            raise ValueError(f"Pagination loop detected at {url}")
        navigate(page, url, policy, delay)
        name, total, cards, next_href = read_category(page)
        if expected is not None and category_name != name:
            raise ValueError(f"Category name changed from {category_name!r} to {name!r}")
        if total not in reported_totals:
            if reported_totals:
                warn(f"{name}: advertised total changed from {reported_totals} to {total} on {url}")
            reported_totals.append(total)
        if expected is None:
            expected = total
        category_name = name
        timestamp = utc_now()
        rows = [
            observation(card, category=name, page_url=url, run_id=run_id, observed_at=timestamp)
            for card in cards
        ]
        identifiers = [row["product_url"] for row in rows]
        if len(set(identifiers)) != len(identifiers) or seen.intersection(identifiers):
            warn(f"{name}: repeated products on {url}; raw page observations retained")
        next_url = collection_url(next_href) if next_href else ""
        if next_url:
            current_page = int(parse_qs(urlsplit(url).query).get("page", ["1"])[0])
            next_page = int(parse_qs(urlsplit(next_url).query).get("page", ["1"])[0])
            if urlsplit(next_url).path != initial_path or next_page != current_page + 1:
                raise ValueError(f"Invalid pagination transition from {url} to {next_url}")
        write_rows(rows)
        seen.update(identifiers)
        visited.add(url)
        observation_count += len(rows)
        page_results.append({
            "url": url, "reported_total": total, "observed_at": timestamp,
            "observations": len(rows),
        })
        LOGGER.info("%s: page %d, %d products, %d unique / %d advertised", name, len(visited), len(rows), len(seen), total)
        url = next_url
    if reported_totals and len(seen) != reported_totals[-1]:
        warn(f"{category_name}: last advertised total {reported_totals[-1]}, collected {len(seen)} unique products")
    return {
        "name": category_name, "url": BASE_URL + initial_path,
        "pages": len(visited), "expected_products": expected, "products": len(seen),
        "observations": observation_count, "reported_totals": reported_totals,
        "page_results": page_results, "warnings": warnings,
    }


def run(
    categories: list[str], all_categories: bool, output: Path, delay: float, *,
    main_categories: bool = False, excluded_categories: list[str] | None = None,
) -> Path:
    started_at = utc_now()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    directory = output / run_id
    directory.mkdir(parents=True, exist_ok=False)
    basename = f"scrape_farmacorp_{run_id.split('_')[0]}"
    snapshot = SnapshotWriter(directory, basename, list(Observation.__annotations__))
    output_files = snapshot.files
    manifest: dict[str, object] = {
        "run_id": run_id, "started_at": started_at, "status": "running",
        "requested_categories": categories, "all_categories": all_categories,
        "main_categories": main_categories,
        "excluded_categories": excluded_categories or [],
        "observations": 0, "categories": [],
        "output_files": output_files,
    }
    summary = directory / "summary.json"

    def save_summary() -> None:
        temporary = summary.with_suffix(".tmp")
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(summary)

    save_summary()
    completed: list[dict[str, object]] = []
    count = 0
    try:
        with (
            snapshot,
            sync_playwright() as playwright,
        ):
            def write_rows(rows: list[Observation]) -> None:
                nonlocal count
                snapshot.write([dict(row) for row in rows])
                count += len(rows)
                manifest["observations"] = count
                if rows:
                    manifest["active_category"] = rows[0]["category"]
                    manifest["active_page_url"] = rows[0]["page_url"]
                save_summary()

            browser = playwright.chromium.launch(headless=True)
            try:
                context: BrowserContext = browser.new_context(
                    locale="es-BO", timezone_id="America/La_Paz",
                )
                context.set_default_timeout(30_000)
                context.set_default_navigation_timeout(60_000)
                context.route(
                    "**/*",
                    lambda route: route.abort() if route.request.resource_type in
                    {"image", "media", "font"} else route.continue_(),
                )
                response = context.request.get(BASE_URL + "/robots.txt")
                if response.status != 200:
                    raise RuntimeError(f"Cannot verify robots.txt: HTTP {response.status}")
                policy = RobotsPolicy(response.text())
                page = context.new_page()
                if all_categories or main_categories:
                    navigate(page, BASE_URL + "/collections/ofertas", policy, delay)
                    categories = discover_categories(page, main_only=main_categories)
                categories = [
                    url for url in categories if url not in (excluded_categories or [])
                ]
                if not categories:
                    raise ValueError("No categories remain after applying exclusions")
                manifest["requested_categories"] = categories
                save_summary()
                for url in categories:
                    completed.append(collect_category(page, url, policy, delay, run_id, write_rows))
                    manifest["categories"] = completed
                    save_summary()
                manifest["active_category"] = None
                manifest["active_page_url"] = None
            finally:
                browser.close()
        manifest["status"] = (
            "completed_with_warnings" if any(category["warnings"] for category in completed)
            else "completed"
        )
    except BaseException as error:
        manifest["status"] = "failed"
        manifest["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        manifest["finished_at"] = utc_now()
        save_summary()
        LOGGER.info("Snapshot %s: %s (%d observations)", directory, manifest["status"], count)
    return directory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--category", action="append", help="Collection slug; repeat for multiple categories (default: ofertas)",
    )
    selection.add_argument(
        "--all-categories", action="store_true", help="Discover and collect every collection in Categorias",
    )
    selection.add_argument(
        "--main-categories", action="store_true", help="Collect only the top-level Categorias menu collections",
    )
    parser.add_argument(
        "--exclude-category", action="append", default=[],
        help="Collection slug to exclude; repeat to skip multiple collections",
    )
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data" / "farmacorp")
    parser.add_argument("--delay", type=float, default=3.0, help="Seconds before each page (minimum: 2)")
    args = parser.parse_args()
    if not 2 <= args.delay < float("inf"):
        parser.error("--delay must be finite and at least 2 seconds")
    categories = []
    for slug in [*(args.category or ["ofertas"]), *args.exclude_category]:
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", slug):
            parser.error(f"Invalid collection slug: {slug!r}")
    for slug in args.category or ["ofertas"]:
        url = collection_url(f"/collections/{slug}")
        if url not in categories:
            categories.append(url)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(
        categories, args.all_categories, args.output, args.delay,
        main_categories=args.main_categories,
        excluded_categories=[
            collection_url(f"/collections/{slug}") for slug in args.exclude_category
        ],
    )


if __name__ == "__main__":
    main()
