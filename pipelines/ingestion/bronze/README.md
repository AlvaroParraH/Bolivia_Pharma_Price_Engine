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

## Placeholder

`ingest_template.py` is intentionally unimplemented. Use it only as a boundary
placeholder. Before implementing extraction and load logic, agree the source,
approved authentication, data classification, incremental/replay semantics,
error handling, and raw-object ownership. Raw data belongs in Snowflake, not
in this source-code directory.
