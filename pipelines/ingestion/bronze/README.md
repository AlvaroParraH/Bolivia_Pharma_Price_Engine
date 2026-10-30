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

Requests identify as `BoliviaPharmaPriceEngine/0.1`. Collection is sequential,
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

## Placeholder

`ingest_template.py` is intentionally unimplemented. Use it only as a boundary
placeholder. Before implementing extraction and load logic, agree the source,
approved authentication, data classification, incremental/replay semantics,
error handling, and raw-object ownership. Raw data belongs in Snowflake, not
in this source-code directory.
