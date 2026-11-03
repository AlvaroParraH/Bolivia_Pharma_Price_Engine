# Bronze ingestion

**Primary source type selected:** multiple source types.

## Farmacorp collection

`scrape_farmacorp.py` uses Playwright/Chromium to read public collection product cards.
From the project root, collect **every page of Ofertas**:

```bash
uv run --no-env-file --locked python -m pipelines.ingestion.bronze.scrape_farmacorp
```

For another collection or every collection linked in the Categorias menu:

```bash
uv run --no-env-file --locked python -m pipelines.ingestion.bronze.scrape_farmacorp --category beauty
uv run --no-env-file --locked python -m pipelines.ingestion.bronze.scrape_farmacorp --all-categories
```

To collect the remaining **main categories**, without re-collecting Ofertas:

```bash
uv run --no-env-file --locked python -m pipelines.ingestion.bronze.scrape_farmacorp --main-categories --exclude-category ofertas
```

`--main-categories` uses the top-level menu only, excluding nested subcategories
and promotional links. `--exclude-category` accepts a collection slug and can
be repeated. All observations include `category` and `category_url` columns in
CSV, JSONL, and Parquet, so each output file can be filtered by category. The
category value is the collection page's heading (for example, `Beauty` for the
menu entry `Belleza`), not an inferred product classification.

Collection slugs can be repeated with `--category`. The all-category mode
includes linked subcategories and deduplicates identical collection URLs.
A product in multiple categories remains a separate category observation.
The first live run collected Ofertas; the next collection covers the remaining
main categories. An all-category run includes nested collections and may take
substantially longer.

Each invocation creates a distinct timestamped directory under
`data/farmacorp/` (ignored by Git), or under `--output <directory>`, containing:

- `scrape_farmacorp_<timestamp>.jsonl`: one product/category/page observation
  per line (newline-delimited JSON, not a JSON array).
- `scrape_farmacorp_<timestamp>.csv`: the same fields for spreadsheet analysis.
- `scrape_farmacorp_<timestamp>.parquet`: the same fields and rows in compressed
  columnar format. String columns preserve exact price text and nullable fields
  preserve nulls, including columns that contain only nulls in early pages.
- `summary.json`: run ID, timestamps, requested categories, observation count,
  completed category counts, per-page counts/timestamps, and `running`,
  `completed`, `completed_with_warnings`, or `failed` status.
  While running, `active_category` and `active_page_url` identify the last page
  saved; `categories` lists fully traversed categories.

All three data filenames share the run's UTC timestamp, for example
`scrape_farmacorp_20261030T152720Z.csv`. The summary's `output_files` maps each
format to its filename. Unique run directories prevent same-second runs from
overwriting one another. CSV and JSONL are flushed after each page; Parquet is
written incrementally and finalized when the writer closes, including on a
handled collection failure. Abrupt process termination may leave Parquet
unreadable; only consume finalized output and check the summary status.
This naming and Parquet addition apply to future runs only; existing snapshots
are not renamed or converted.

These are local collection snapshots pending an approved warehouse-loading
design, not files to commit or store in the ingestion source directory.
Retain snapshots for historical comparisons. No Snowflake connection is made.
All three scraper summaries include `retailer` for identity validation by the
Azure uploader used by the Airflow DAG.

### Price and product semantics

- `price`: the displayed regular/compare-at price when discounted, otherwise
  the displayed current price.
- `discount_price`: the current discounted price, or JSON null if no discount.
- `current_price`: the price shown as payable now.
- Prices are exact decimal strings in BOB, not binary floating-point numbers.
  Raw displayed price strings and the site's discount label are also saved.
  `discount_percent` is calculated from displayed prices; rounded site labels
  may differ. The generic `Venta` badge is retained as a raw label but does not
  imply a discounted price without a lower current price.
  Multi-buy offers such as `3 x 2` are also retained as raw labels. Without a
  current price below the displayed comparison price, `discount_price` and `discount_percent`
  remain null; no basket-level savings are converted to a per-unit discount.
  These offers are logged and recorded in category warnings. Numeric
  percentage badges without a lower price still fail validation.
- Product name, displayed brand, canonical product URL, product handle, image
  URL, category, page URL, UTC observation time, and run ID preserve provenance.
  The URL handle is not assumed to be a verified SKU or GTIN.
- Availability is only a displayed sold-out badge; null means unknown, not
  confirmed in stock. No stock or transactional API is queried.
- Prices describe the public online store with no branch selected, not
  guaranteed branch prices. Farmacorp's terms state online prices may differ
  from other channels and can change without notice.

The collector follows the next-page link until exhausted, validates page
progression, and compares unique product counts with the displayed totals.
As approved for this live catalog, changing totals and repeated products are
logged and recorded as explicit warnings. Repeated raw page observations are
retained, not silently discarded. Such runs are **completed_with_warnings**:
all linked pages were traversed, but exact catalog coverage is not guaranteed.
Use canonical product URL and category to identify repeated observations.
Errors, invalid pagination, or missing required fields stop the run; partial
output is retained with **failed** status. Rerun to produce a new snapshot.
A completed scrape is not an atomic site-wide snapshot: prices can change
while it runs, so use per-page observation times.
An explicit `No se encontro coincidencias` catalog marker with no products or
next-page link terminates pagination even if the heading retains a nonzero
category count. This discrepancy is recorded as a warning, not exact coverage.
Missing products without that marker and empty pages with a next link still fail.

Requests use Chromium's native User-Agent, without a custom override.
Robots policy checks retain the collector identity `BoliviaPharmaPriceEngine/0.1`.
Collection is sequential,
with a default three-second pause before each page (`--delay`, minimum two).
Images, media, and fonts are not downloaded. The current robots policy is
checked before collection and navigation; filtered/sorted collections,
transactional pages, off-site redirects, and unexpected pagination are refused.
HTTP errors, including 429, stop the run; there is no access-control bypass.
Review the site's terms and robots policy again before expanding collection.

## Farmacias Chavez collection

`scrape_farmacias_chavez.py` uses one headless Chromium instance and one reused
page to collect every paginated main-menu category, including promotional
categories. Nested subcategories are not independently crawled. Repeat products
across categories are retained with their category names for filtering.

```bash
uv run --no-env-file --locked python -m pipelines.ingestion.bronze.scrape_farmacias_chavez --allow-missing-robots
```

For a bounded collection, specify exact menu labels:

```bash
uv run --no-env-file --locked python -m pipelines.ingestion.bronze.scrape_farmacias_chavez --category "Ofertas Del Mes" --allow-missing-robots
```

The site currently returns an HTML app page for `robots.txt`, not usable
crawling rules. `--allow-missing-robots` records explicit approval to proceed
despite this uncertainty. Without that approval the collector stops. HTTP
403/429/server errors are not treated as missing rules. Check the site's
[terms](https://www.farmaciaschavez.com.bo/TermsAndConditions) before expanding
or republishing data; public visibility is not a license to reuse protected
content. This collector stores product/price facts, not descriptions or images.

Each run saves a unique directory under `data/farmacias_chavez/` (ignored by
Git), with matching `scrape_farmacias_chavez_<UTC timestamp>.csv`, `.jsonl`,
and `.parquet` files plus `summary.json`. The summary records requested and
completed categories, page counts, active page, observation count, warnings,
and completion/failure status. CSV/JSONL flush per page; Parquet finalizes when
the writer closes. Both retailers use the shared `snapshot.py` output writer.

Price meanings match Farmacorp: `price` is the regular price, `discount_price`
is the lower current price or null, and `current_price` is payable now.
Exact decimal strings avoid float rounding. Raw prices, promotion labels,
calculated discount percentages, product ID/URL, category/URL, image URL,
and UTC observation times are retained. The ID is the retailer URL suffix,
not a verified barcode. `name` comes from image alt text; `display_name`
preserves the potentially truncated visible card title. Brand is not inferred
when absent from the cards. Availability is unknown unless explicitly shown;
absence of an unavailable label does not prove stock.

The market context is the public site **without a delivery location selected**.
The site advises selecting a location for the nearest store catalog, so this
is not a branch-specific price/availability guarantee. Its terms state prices
are in national currency, include tax, and may change without notice.

Pagination uses the public next button, waits for both the URL and product
cards to change, checks page numbers and terminal button state, and records
changing totals/overlaps as warnings. Full repeated pages, required-field
failures, or invalid navigation stop the run and mark partial output failed.
Three-second minimum pauses apply between pages/categories; images, media,
and fonts are blocked. No accounts, carts, purchases, login bypass, private
API scraping, Snowflake connection, or automated publishing is involved.

## Hipermaxi Farmacia Calacoto

`scrape_hipermaxi.py` completed a full live collection of all 14 main categories:
4,366 unique products (318 discounted) across 96 scroll batches. All categories
reached explicit terminal markers and CSV/JSONL/Parquet records matched.
Initial pilots encountered Radware validation and a fixed readiness bug.
Use approved access and do not bypass challenges. Review
[Hipermaxi terms](https://informacion.hipermaxi.com/terminos-y-condiciones-generales/)
before collecting or republishing data.

Once access is approved, the CLI supports:

```bash
uv run --no-env-file --locked python -m pipelines.ingestion.bronze.scrape_hipermaxi --category farmacia-genericos
```

Omitting `--category` selects all discovered main-menu categories (14 observed).
Use repeatable `--exclude-category <slug>` to omit a discovered category.
Airflow passes `--exclude-category no-comestible`; local runs keep all categories
unless exclusions are explicitly supplied. Summaries record `excluded_categories`
and the actual requested scope. Unknown exclusions or an empty remaining scope fail.
The collector uses an already-loaded main category directly. If navigation
lands on a subcategory, it selects “Todo” to return to the main category.
It uses one reused browser/page (headless by default), pauses at least three seconds between
navigations and scroll batches, and blocks image/media/font downloads.
The bottom status sentinel triggers infinite scrolling; completion requires
an explicit terminal/empty-products message. Timeouts, missing sentinels,
HTTP errors, unexpected redirects and invalid records fail the snapshot, rather
than treating incomplete output as success. Repeated product IDs are retained
with warnings. Main categories are not separately expanded into nested crawls.
The status sentinel is scrolled into view directly using an instant DOM scroll,
without waiting for its animated loading indicator to become stable. Collection
still waits for additional products or an explicit terminal message before
proceeding; scrolling alone never establishes completion.

The shared writer saves `scrape_hipermaxi_<UTC timestamp>.csv`, `.jsonl`, and
`.parquet` plus `summary.json` in a unique ignored `data/hipermaxi/` directory.
The summary records requested/completed categories, active category/batch,
observation counts and failure status; partial output remains on failure.
Rows include La Paz/Farmacia Calacoto context, category name/URL, product
ID/URL/name, batch, UTC observation time, raw prices, discount labels,
calculated discount percentage and image URL metadata. Product IDs are not
verified barcodes; missing availability labels mean unknown stock.
Prices use exact BOB decimal strings with the same regular/current/discount
semantics as the other collectors. Cross-category observations are preserved.
No accounts, carts, private API collection or Snowflake access is used.
The site's usable robots rules are checked with the existing longest-match
policy implementation; bot validation is a separate access restriction.

All three retailers' browser sessions use Playwright Chromium's native User-Agent, including
its actual platform/version, rather than a custom-only identifier or a copied
Chrome/VS Code version. Headless mode retains its native headless identifier.
The existing robots policy still checks rules for the collector identity
`BoliviaPharmaPriceEngine/0.1`; Farmacorp and Chavez also retain this identity for
robots policy checks. Locale `es-BO` and timezone `America/La_Paz` are unchanged.
This compatibility change does not guarantee acceptance by bot validation.

Each navigation, “Todo” selection and scroll batch waits for `--delay`
(default/minimum three seconds) plus a random 0-2 seconds. With defaults,
pauses are 3-5 seconds. This is operation-level pacing, not a delay on every
script, image or background request. The summary records the minimum and extra
delay range. It does not disguise the collector or guarantee validation success.
The collector waits up to 60 seconds for the category heading and products or
an explicit empty/end message at the main category URL; a hidden “Todo” link
does not block an already-loaded main category. On a subcategory URL, it instead
waits for a visible “Todo” link targeting the requested main category.
After selection, it waits up to 60 seconds for products or an explicit empty/end
message. Missing content still fails the run rather than producing empty success.

### Optional manual validation

For approved collection, `--interactive` launches **visible Chromium from the
start**. It allows navigation to the exact HTTPS host `validate.perfdrive.com`,
pauses collection, brings the window forward and logs instructions for you
to interact manually. Challenge images/fonts/media are allowed while it is
displayed; catalog resource blocking remains unchanged. No challenge clicks,
solvers, stealth headers, session import/export or automatic validation are used.
The HTTPS `newassets.hcaptcha.com` embedded frame is allowed only while the
interactive Radware page is displayed; top-level navigation to it stays blocked.

```bash
uv run --no-env-file --locked python -m pipelines.ingestion.bronze.scrape_hipermaxi --interactive --validation-timeout 300 --category farmacia-genericos
```

The timeout is a finite positive number of seconds (default 300 per challenge).
No terminal input is needed: the collector waits for the browser to leave the
validation host, checks the Calacoto URL and robots rules, then resumes in the
same in-memory session. Unknown destinations, timeout or closing the window
fail the snapshot and close the browser. The summary records interactive mode
and its timeout. HTTP errors on catalog pages still stop collection.
If validation interrupts a DOM operation, it is retried once; writes and
categories are not blindly replayed. A changed category or changed previously
collected product sequence stops the run to avoid skipping products after a
reload. Repeated validation during the retry stops the run.

Without `--interactive`, validation remains blocked and no window is opened.
Manual validation does not establish collection permission, guarantee access,
or prove future live coverage. Offline browser fixtures test the manual-return
workflow; one live pilot also returned from validation before a separate
category-readiness failure. The later full collection completed successfully.

## Placeholder

`ingest_template.py` is intentionally unimplemented. Use it only as a boundary
placeholder. Before implementing extraction and load logic, agree the source,
approved authentication, data classification, incremental/replay semantics,
error handling, and raw-object ownership. Raw data belongs in Snowflake, not
in this source-code directory.
