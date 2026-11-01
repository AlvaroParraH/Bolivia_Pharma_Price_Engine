"""Collect Hipermaxi Farmacia Calacoto categories through public infinite scroll."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
from pathlib import Path
import random
import re
import time
from typing import TypeVar
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

from playwright.sync_api import (
    BrowserContext, Error as PlaywrightError, Page,
    TimeoutError as PlaywrightTimeoutError, sync_playwright,
)

from pipelines.ingestion.bronze.snapshot import SnapshotWriter
from pipelines.ingestion.bronze.scrape_farmacorp import RobotsPolicy


BASE_URL = "https://www.hipermaxi.com"
BRANCH_PATH = "/la-paz/farmacia-calacoto"
BRANCH_URL = BASE_URL + BRANCH_PATH
LOGGER = logging.getLogger(__name__)
T = TypeVar("T")
FIELDS = [
    "run_id", "observed_at", "retailer", "city", "branch", "category",
    "category_url", "page_url", "batch", "product_id", "product_url", "name",
    "currency", "price", "discount_price", "current_price", "discount_percent",
    "discount_label", "availability_label", "image_url", "current_price_text",
    "regular_price_text", "market_context",
]
EXTRACT_CARDS = """cards => cards.map(card => {
    const prices = [...card.querySelectorAll('[aria-label="Precio del producto"] span')]
        .map(n=>n.textContent.trim()).filter(t=>t.startsWith('Bs'));
    return {
        href:card.querySelector('a[href*="/producto/"]')?.getAttribute('href') || null,
        name:card.querySelector('h3')?.textContent.trim() || null,
        current_price_text:prices[0] || null,
        regular_price_text:prices[1] || null,
        discount_label:[...card.querySelectorAll('span')].map(n=>n.textContent.trim())
            .find(t=>/^-\\d+% OFF$/.test(t)) || null,
        availability_label:card.innerText.match(/agotado|sin stock|no disponible/i)?.[0] || null,
        image_url:card.querySelector('img')?.getAttribute('src') || null
    };
})"""
WAIT_FOR_BATCH = """previous => {
    const main = document.querySelector('main');
    return main && (
        main.querySelectorAll('article').length > previous ||
        /Has visto todos los productos|No se encontraron productos|No hay productos/.test(main.innerText)
    );
}"""
WAIT_FOR_CATEGORY = """url => {
    const main = document.querySelector('main');
    if (!main || !main.querySelector('h1, h2')) return false;
    if (location.href === url) {
        return main.querySelectorAll('article').length > 0 ||
            /Has visto todos los productos|No se encontraron productos|No hay productos/.test(main.innerText);
    }
    return location.href.startsWith(url + '/') &&
        [...document.querySelectorAll('a[href]')].some(link =>
            link.textContent.trim() === 'Todo' && link.href === url &&
            link.getClientRects().length > 0);
}"""
CONTENT_TIMEOUT_MS = 80_000
CATEGORY_READINESS_RETRIES = 3


def pause(delay: float) -> None:
    if not 0 <= delay < float("inf"):
        raise ValueError("delay must be finite and nonnegative")
    time.sleep(max(3.0, delay) + random.uniform(0, 2))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def category_url(url: str) -> str:
    absolute = urljoin(BASE_URL, url)
    parts = urlsplit(absolute)
    if (
        parts.scheme != "https" or parts.netloc != "www.hipermaxi.com"
        or not re.fullmatch(re.escape(BRANCH_PATH) + r"/categoria/[a-z0-9-]+", parts.path)
        or parts.query or parts.fragment
    ):
        raise ValueError(f"Not a Calacoto main category URL: {url}")
    return absolute


def parse_price(text: str) -> Decimal:
    match = re.fullmatch(r"Bs\s+(\d{1,3}(?:,\d{3})*|\d+)\.(\d{2})", text.strip())
    if match is None:
        raise ValueError(f"Unrecognized Hipermaxi BOB price: {text!r}")
    return Decimal(match[1].replace(",", "") + "." + match[2])


def observation(
    card: dict[str, str | None], name: str, url: str, batch: int,
    run_id: str, timestamp: str,
) -> dict[str, str | None]:
    if not card["href"] or not card["name"] or not card["current_price_text"]:
        raise ValueError(f"Missing product name, link or price: {card!r}")
    product_url = urljoin(BASE_URL, card["href"])
    parts = urlsplit(product_url)
    match = re.fullmatch(re.escape(BRANCH_PATH) + r"/producto/(\d+)/[^/]+", parts.path)
    if parts.netloc != "www.hipermaxi.com" or parts.scheme != "https" or not match or parts.query or parts.fragment:
        raise ValueError(f"Unexpected product URL: {product_url}")
    current = parse_price(card["current_price_text"])
    regular = parse_price(card["regular_price_text"]) if card["regular_price_text"] else current
    if regular < current:
        raise ValueError(f"Regular price below current price: {product_url}")
    discounted = regular > current
    if card["discount_label"] and not discounted:
        raise ValueError(f"Discount badge without lower price: {product_url}")
    return {
        "run_id": run_id, "observed_at": timestamp, "retailer": "hipermaxi",
        "city": "La Paz", "branch": "Farmacia Calacoto", "category": name,
        "category_url": url, "page_url": url, "batch": str(batch),
        "product_id": match[1], "product_url": product_url, "name": card["name"],
        "currency": "BOB", "price": f"{regular:.2f}",
        "discount_price": f"{current:.2f}" if discounted else None,
        "current_price": f"{current:.2f}",
        "discount_percent": f"{(regular-current)/regular*100:.2f}" if discounted else None,
        "discount_label": card["discount_label"], "availability_label": card["availability_label"],
        "image_url": urljoin(BASE_URL, card["image_url"]) if card["image_url"] else None,
        "current_price_text": card["current_price_text"], "regular_price_text": card["regular_price_text"],
        "market_context": "la_paz_farmacia_calacoto_public_web",
    }


def robots(context: BrowserContext) -> RobotsPolicy:
    response = context.request.get(BASE_URL + "/robots.txt")
    text = response.text()
    if response.status != 200 or "<html" in text.lower() or "user-agent:" not in text.lower():
        raise RuntimeError(f"No usable Hipermaxi robots.txt (HTTP {response.status})")
    return RobotsPolicy(text)


def is_branch_url(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.netloc == "www.hipermaxi.com" and (
        parts.path == BRANCH_PATH or parts.path.startswith(BRANCH_PATH + "/")
    )


def is_validation_url(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.netloc == "validate.perfdrive.com"


def permitted_navigation(url: str, policy: RobotsPolicy, interactive: bool) -> bool:
    if interactive and is_validation_url(url):
        return True
    if not is_branch_url(url):
        LOGGER.error("Blocked navigation outside Calacoto pharmacy to %s", urlsplit(url).netloc)
        return False
    try:
        policy.check(url)
    except ValueError:
        LOGGER.error("Blocked navigation disallowed by robots.txt")
        return False
    return True


def wait_for_catalog(page: Page, policy: RobotsPolicy, validation_timeout: float) -> bool:
    challenged = is_validation_url(page.url)
    if challenged and validation_timeout > 0:
        LOGGER.warning(
            "Manual validation required. Complete the challenge in the open Chromium window. "
            "Collection is paused for up to %g seconds; it resumes only on return to Calacoto. "
            "Close the window to cancel.", validation_timeout,
        )
        page.bring_to_front()
        try:
            page.wait_for_url(
                lambda url: not is_validation_url(url),
                wait_until="domcontentloaded", timeout=validation_timeout * 1000,
            )
        except PlaywrightTimeoutError:
            raise RuntimeError("Manual validation timed out; collection stopped.") from None
    if not is_branch_url(page.url):
        raise RuntimeError(
            f"Navigation left Calacoto pharmacy for {urlsplit(page.url).netloc}; "
            "automated access may require site approval. No validation bypass attempted."
        )
    policy.check(page.url)
    if challenged:
        LOGGER.info("Returned to Calacoto after manual validation; resuming in the same browser session.")
    return challenged


def catalog_action(
    page: Page, policy: RobotsPolicy, validation_timeout: float, action: Callable[[], T],
) -> T:
    wait_for_catalog(page, policy, validation_timeout)
    try:
        result = action()
    except PlaywrightError:
        if not is_validation_url(page.url):
            raise
        wait_for_catalog(page, policy, validation_timeout)
    else:
        if not is_validation_url(page.url):
            wait_for_catalog(page, policy, validation_timeout)
            return result
        wait_for_catalog(page, policy, validation_timeout)
    # Retry only the interrupted DOM operation, never a write or an entire category.
    result = action()
    if wait_for_catalog(page, policy, validation_timeout):
        raise RuntimeError("Validation recurred during the interrupted operation; collection stopped.")
    return result


def navigate(
    page: Page, url: str, policy: RobotsPolicy, delay: float, validation_timeout: float = 0,
) -> None:
    policy.check(url)
    pause(delay)
    try:
        response = page.goto(url, wait_until="domcontentloaded")
    except PlaywrightError:
        if not is_validation_url(page.url):
            raise
        wait_for_catalog(page, policy, validation_timeout)
        return
    if is_validation_url(page.url):
        wait_for_catalog(page, policy, validation_timeout)
        return
    if response is None or response.status >= 400:
        raise RuntimeError(f"Navigation failed: {url}; HTTP {response.status if response else 'none'}")
    wait_for_catalog(page, policy, validation_timeout)


def discover_categories(page: Page) -> list[dict[str, str]]:
    entries = page.get_by_role("navigation", name="Menú principal de categorías").locator(
        'a[href*="/categoria/"]',
    ).evaluate_all("ns=>ns.map(n=>({name:n.textContent.trim(),url:n.getAttribute('href')}))")
    result: dict[str, dict[str, str]] = {}
    for entry in entries:
        url = category_url(entry["url"])
        if not entry["name"]:
            raise ValueError("Unnamed category in main menu")
        result.setdefault(url, {"name": entry["name"], "url": url})
    if not result:
        raise ValueError("No Calacoto categories found")
    return list(result.values())


def open_all_products(
    page: Page, url: str, policy: RobotsPolicy, delay: float, validation_timeout: float = 0,
) -> None:
    for attempt in range(CATEGORY_READINESS_RETRIES + 1):
        try:
            _open_all_products(page, url, policy, delay, validation_timeout)
            return
        except PlaywrightTimeoutError:
            if attempt == CATEGORY_READINESS_RETRIES:
                LOGGER.error("Category readiness timed out after %d attempts: %s", attempt + 1, url)
                raise
            wait_for_catalog(page, policy, validation_timeout)
            LOGGER.warning(
                "Category readiness timed out; retry %d/%d: %s",
                attempt + 1, CATEGORY_READINESS_RETRIES, url,
            )


def _open_all_products(
    page: Page, url: str, policy: RobotsPolicy, delay: float, validation_timeout: float,
) -> None:
    navigate(page, url, policy, delay, validation_timeout)
    catalog_action(
        page, policy, validation_timeout,
        lambda: page.wait_for_function(
            WAIT_FOR_CATEGORY, arg=url, timeout=CONTENT_TIMEOUT_MS,
        ),
    )
    if page.url != url:
        all_link = page.get_by_role("link", name="Todo", exact=True)
        catalog_action(
            page, policy, validation_timeout,
            lambda: all_link.wait_for(timeout=CONTENT_TIMEOUT_MS),
        )
        pause(delay)
        catalog_action(page, policy, validation_timeout, all_link.click)
        catalog_action(
            page, policy, validation_timeout,
            lambda: page.wait_for_url(url, timeout=CONTENT_TIMEOUT_MS),
        )
    catalog_action(
        page, policy, validation_timeout,
        lambda: page.wait_for_function(WAIT_FOR_BATCH, arg=0, timeout=CONTENT_TIMEOUT_MS),
    )


def collect_category(
    page: Page, entry: dict[str, str], policy: RobotsPolicy, delay: float,
    run_id: str, write: Callable[[list[dict[str, str | None]]], None],
    validation_timeout: float = 0,
) -> dict[str, object]:
    url, name = entry["url"], entry["name"]
    open_all_products(page, url, policy, delay, validation_timeout)
    processed = 0
    processed_links: list[str | None] = []
    seen: set[str] = set()
    warnings: list[str] = []
    batches: list[dict[str, object]] = []
    while True:
        wait_for_catalog(page, policy, validation_timeout)
        if page.url != url:
            raise ValueError(f"Category changed during collection: {page.url}")
        cards = catalog_action(
            page, policy, validation_timeout,
            lambda: page.locator("main article").evaluate_all(EXTRACT_CARDS),
        )
        if page.url != url or [card["href"] for card in cards[:processed]] != processed_links:
            raise ValueError("Category or previously collected products changed; snapshot interrupted")
        fresh = cards[processed:]
        timestamp = utc_now()
        rows = [observation(card, name, url, len(batches)+1, run_id, timestamp) for card in fresh]
        identifiers = [row["product_id"] for row in rows]
        if seen.intersection(identifiers) or len(set(identifiers)) != len(identifiers):
            message = f"Repeated product IDs in batch {len(batches)+1}; observations retained"
            warnings.append(message)
            LOGGER.warning("%s: %s", name, message)
        seen.update(identifier for identifier in identifiers if identifier is not None)
        if rows:
            write(rows)
            batches.append({"batch": len(batches)+1, "observations": len(rows), "observed_at": timestamp})
            processed = len(cards)
            processed_links = [card["href"] for card in cards]
            LOGGER.info("%s: batch %d, %d observations, %d unique products", name, len(batches), processed, len(seen))
        main_text = catalog_action(
            page, policy, validation_timeout, lambda: page.locator("main").inner_text(),
        )
        if page.url != url:
            raise ValueError("Category changed while checking completion; snapshot interrupted")
        if re.search(r"Has visto todos los productos|No se encontraron productos|No hay productos", main_text):
            break
        sentinel = page.locator('main [role="status"]').last
        if not sentinel.count():
            raise ValueError("Missing scroll sentinel and no explicit end-of-products marker")
        pause(delay)
        catalog_action(page, policy, validation_timeout, sentinel.scroll_into_view_if_needed)
        catalog_action(
            page, policy, validation_timeout,
            lambda: page.wait_for_function(WAIT_FOR_BATCH, arg=processed),
        )
    return {
        "name": name, "url": url, "batches": batches, "observations": processed,
        "products": len(seen), "warnings": warnings, "terminal_marker": True,
    }


def run(
    output: Path, selected: list[str] | None, delay: float, *,
    interactive: bool = False, validation_timeout: float = 300,
) -> Path:
    if not 0 < validation_timeout < float("inf"):
        raise ValueError("validation_timeout must be finite and positive")
    manual_timeout = validation_timeout if interactive else 0
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = timestamp + "_" + uuid4().hex[:8]
    directory = output / run_id
    directory.mkdir(parents=True, exist_ok=False)
    snapshot = SnapshotWriter(directory, f"scrape_hipermaxi_{timestamp}", FIELDS)
    manifest: dict[str, object] = {
        "run_id": run_id, "started_at": utc_now(), "status": "running",
        "branch_url": BRANCH_URL, "requested_categories": selected or [],
        "categories": [], "observations": 0, "output_files": snapshot.files,
        "interactive": interactive, "validation_timeout_seconds": manual_timeout,
        "minimum_delay_seconds": max(3.0, delay), "extra_delay_range_seconds": [0, 2],
    }
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
            manifest["active_batch"] = rows[0]["batch"]
        save()

    save()
    try:
        with snapshot, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=not interactive)
            try:
                context = browser.new_context(locale="es-BO", timezone_id="America/La_Paz")
                context.set_default_timeout(30_000)
                context.set_default_navigation_timeout(60_000)
                policy = robots(context)
                page = context.new_page()
                context.route("**/*", lambda route: route.abort() if (
                    (route.request.resource_type in {"image", "media", "font"}
                     and not (interactive and is_validation_url(page.url)))
                    or (route.request.is_navigation_request()
                        and not (
                            interactive and is_validation_url(page.url)
                            and route.request.frame != page.main_frame
                            and urlsplit(route.request.url).scheme == "https"
                            and urlsplit(route.request.url).netloc == "newassets.hcaptcha.com"
                        )
                        and not permitted_navigation(route.request.url, policy, interactive))
                ) else route.continue_())
                navigate(page, BRANCH_URL, policy, delay, manual_timeout)
                entries = catalog_action(
                    page, policy, manual_timeout, lambda: discover_categories(page),
                )
                if selected:
                    slugs = {entry["url"].rsplit("/", 1)[1] for entry in entries}
                    if set(selected) - slugs:
                        raise ValueError(f"Unknown category slugs: {set(selected)-slugs}")
                    entries = [entry for entry in entries if entry["url"].rsplit("/", 1)[1] in selected]
                manifest["requested_categories"] = entries
                save()
                for entry in entries:
                    completed.append(collect_category(
                        page, entry, policy, delay, run_id, write, manual_timeout,
                    ))
                    manifest["categories"] = completed
                    save()
            finally:
                browser.close()
        manifest["active_category"] = None
        manifest["active_batch"] = None
        manifest["status"] = "completed_with_warnings" if any(item["warnings"] for item in completed) else "completed"
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
    parser.add_argument("--category", action="append", help="Main category slug; repeat, defaults to all Calacoto pharmacy categories")
    parser.add_argument(
        "--delay", type=float, default=3,
        help="Minimum pause before navigation, category selection and scroll batches "
        "(at least 3 seconds, plus 0-2 seconds random extra delay)",
    )
    parser.add_argument(
        "--interactive", action="store_true",
        help="Open visible Chromium and pause for manual Radware validation (no automatic solving)",
    )
    parser.add_argument(
        "--validation-timeout", type=float, default=300,
        help="Seconds allowed for each manual validation in interactive mode (default: 300)",
    )
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[3] / "data" / "hipermaxi")
    args = parser.parse_args()
    if not 3 <= args.delay < float("inf"):
        parser.error("--delay must be finite and at least three seconds")
    if not 0 < args.validation_timeout < float("inf"):
        parser.error("--validation-timeout must be finite and positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(
        args.output, args.category, args.delay,
        interactive=args.interactive, validation_timeout=args.validation_timeout,
    )


if __name__ == "__main__":
    main()
