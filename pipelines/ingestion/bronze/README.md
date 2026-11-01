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
The collector uses an already-loaded main category directly. If navigation
lands on a subcategory, it selects “Todo” to return to the main category.
It uses one reused browser/page (headless by default), pauses at least three seconds between
navigations and scroll batches, and blocks image/media/font downloads.
The bottom status sentinel triggers infinite scrolling; completion requires
an explicit terminal/empty-products message. Timeouts, missing sentinels,
HTTP errors, unexpected redirects and invalid records fail the snapshot, rather
than treating incomplete output as success. Repeated product IDs are retained
with warnings. Main categories are not separately expanded into nested crawls.

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
The collector waits up to 80 seconds for the category heading and products or
an explicit empty/end message at the main category URL; a hidden “Todo” link
does not block an already-loaded main category. On a subcategory URL, it instead
waits for a visible “Todo” link targeting the requested main category.
After selection, it waits up to 80 seconds for products or an explicit empty/end
message. Category-opening timeouts trigger up to three retries after the initial
attempt (four attempts total), reopening the category with the existing pacing.
Each readiness wait has its own 80-second limit, not a single overall deadline.
Retries happen before category rows are written; collected batches and writes
are never replayed. HTTP errors, policy failures, and failed manual validation
still stop the run without these retries. Missing content after all attempts
fails the run rather than producing empty success.

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

## Upload snapshots to Azure Blob Storage

Upload an existing finalized run without scraping again:

```bash
uv run --no-env-file --locked python -m pipelines.ingestion.bronze.upload_snapshot \
  data/farmacorp/<run_directory> --retailer farmacorp
```

Use `farmacias_chavez` or `hipermaxi` for the other retailers. The shared
`upload_snapshot.py` uploader reads the explicitly selected local `.env`
(`--env-file <path>` to override) using `python-dotenv`, without modifying the
process environment or interpolating variables. Define
`AZURE_STORAGE_CONNECTION_STRING` and `AZURE_STORAGE_CONTAINER` there.
Never commit those credentials; rotate exposed keys. Tenant ID is not needed
by the uploader. Snowflake's storage integration does not authenticate Python
uploads; this uploader needs separate Azure write access.

Only the Parquet file is uploaded, to
`bronze/<retailer>/<current_UTC_upload_date_YYYYMMDD>/<original_filename>.parquet`.
There is no run-ID folder and no uploaded summary. The date is the upload date,
not the scrape date; the original filename keeps its scrape timestamp.
The selected local run is removed by default after successful upload and
verification; no cleanup flag is required. This deletes its CSV, JSONL, Parquet, and local summary,
then removes the empty run directory; only Parquet is stored in Azure. The run
directory must be named after its summary's `run_id` and contain exactly those
four regular files. Unexpected files, subdirectories, or symlinks prevent cleanup
and fail validation before upload. No recursive deletion is used.

Upload/verification failures retain local files. A cleanup failure after upload
is reported separately and can leave partially removed local files; inspect the
run and existing blob before retrying. Scraping and uploading remain separate
commands; this behavior does not change scraper output or trigger a live upload.
Python callers can explicitly pass `delete_after_upload=False` to retain files.

The local summary must be `completed` or `completed_with_warnings`, with a
positive observation count matching the finalized, readable Parquet data.
The uploader checks row provenance and logs a warning for warning-status runs.
It uploads with overwrite disabled and verifies blob size, stored MD5, and
SHA-256 metadata; Azure SDK transfer checksums validate transferred chunks.
This is not a separate download-and-rehash verification.
Missing/malformed snapshots, failed runs, collisions, and upload/verification
errors fail explicitly. Azure exception details are withheld from CLI output
to avoid leaking credential-bearing requests.

The SDK retries transient requests, but an already-existing destination is
never overwritten or silently treated as success. If a previous attempt
uploaded before failing verification, inspect that blob before retrying.
Retries on a different UTC date produce a different destination: warehouse
loading must still prevent duplicate ingestion using the record run identity.
No container is created automatically and no Snowflake operation is performed.

## Load Parquet into Snowflake

The following local, unexecuted SQL scripts load all matching Parquet snapshots
across upload-date folders in each retailer stage:

- [load_farmacorp.sql](load_farmacorp.sql)
- [load_farmacias_chavez.sql](load_farmacias_chavez.sql)
- [load_hipermaxi.sql](load_hipermaxi.sql)

They target `BOLIVIA_PHARMA_PRICE_ENGINE.BRONZE.SCRAPED_<RETAILER>_PRICES`.
Create the approved tables and
[external stages](../../../infra/snowflake/migrations/bronze/stages/README.md)
first, creating the shared Bronze `PARQUET_SNAPSHOTS_FORMAT` before the stages,
then apply the ingestor grants. COPY inherits that named format from its stage;
it has no inline format override. Execute only after separate live approval
using `PHARMA_DEV_INGESTOR` and `COMPUTE_WH`, not a runtime `ACCOUNTADMIN` role.
No automatic scheduling, Snowpipe, role assignment, or table creation is included.

Each script maps every scraper field by its case-sensitive Parquet key,
explicitly casts prices to decimals and offset-bearing observation strings to
`TIMESTAMP_TZ`, and preserves optional nulls and raw display text. Hipermaxi's
batch becomes an integer. These casts assume the existing scraper contract:
two-decimal prices/percentages, integer batches, and explicit UTC offsets.
Snowflake numeric casts can round overprecision; these scripts are not a
general validator for externally supplied files.

`SOURCE_FILE` records `METADATA$FILENAME` and `SOURCE_ROW_NUMBER` records the
one-based file row. `LOADED_AT` uses the table default. `ABORT_STATEMENT`
rejects conversion/load errors rather than skipping rows or converting errors
to nulls. Inspect every COPY result for errors and rows loaded; parser/linter
checks alone do not prove Snowflake execution.

Files remain in Azure (`PURGE = FALSE`). `FORCE = FALSE` uses Snowflake's
table-specific file-load history to skip known loaded files; uncertain-history
files are not automatically loaded. This is not permanent run-level deduplication:
load history expires, table replacement loses history, and the same run
reuploaded under a different date/path can be loaded again. Do not force reloads
or rename/reupload runs as a retry strategy without an explicit replay decision.
Legitimate repeated rows and cross-category observations remain intact.

All matching files include previously uploaded pilot snapshots as well as full
runs. The uploader validated their local summaries, but those summaries are not
in Azure. Reviewing uploaded `scrape_status` metadata and the desired historical
scope remains a deployment prerequisite. Do not infer atomic catalog coverage.

## Snowflake table definitions

Local [Bronze table migrations](../../../infra/snowflake/migrations/bronze/tables/README.md)
define one historical observation table per scraper, with typed decimal prices,
offset-aware observation timestamps, source-specific fields, raw displayed
prices, and load metadata. They have not been executed in Snowflake.
The guide documents required conversions from the string-based snapshots,
null handling, run-status checks, and replay safeguards. Local stages and COPY scripts are now defined separately; they have not been
executed. Scraper output behavior is unchanged.

## Placeholder

`ingest_template.py` is intentionally unimplemented. Use it only as a boundary
placeholder. Before implementing extraction and load logic, agree the source,
approved authentication, data classification, incremental/replay semantics,
error handling, and raw-object ownership. Raw data belongs in Snowflake, not
in this source-code directory.
