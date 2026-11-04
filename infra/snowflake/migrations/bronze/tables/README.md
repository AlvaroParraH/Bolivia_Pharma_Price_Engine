# Bronze table migrations

Place reviewed SQL changes for tables in the Bronze schema here. No migration
runner or execution order is configured yet.

## Scraper observation tables

| Migration | Table |
|---|---|
| [scraped_farmacorp_prices.sql](scraped_farmacorp_prices.sql) | `BRONZE.SCRAPED_FARMACORP_PRICES` |
| [scraped_farmacias_chavez_prices.sql](scraped_farmacias_chavez_prices.sql) | `BRONZE.SCRAPED_FARMACIAS_CHAVEZ_PRICES` |
| [scraped_hipermaxi_prices.sql](scraped_hipermaxi_prices.sql) | `BRONZE.SCRAPED_HIPERMAXI_PRICES` |

These are local definitions, not deployed tables. Before execution, explicitly
select the approved database and role, confirm that its `BRONZE` schema exists,
and review the target objects. The scripts fully qualify targets in
`BOLIVIA_PHARMA_PRICE_ENGINE.BRONZE`. Scripts use `CREATE TABLE`, not
`CREATE OR REPLACE` or `IF NOT EXISTS`:
an existing table causes an error rather than data loss or silently accepting
an incompatible definition. No schema, grants, stages, or loader are created.

### Grain and history

One row represents a scraper observation in a run, category, and page (or
Hipermaxi scroll batch). Load new runs by appending; do not overwrite previous
months or deduplicate by product alone. Repeated page/batch and cross-category
observations remain valid Bronze records. Product IDs and Farmacorp handles are
strings, not verified barcodes or cross-retailer matching keys.

### Types and loading contract

- Columns retain the scraper field names and order, followed by load metadata.
  Prices use exact `NUMBER(18, 2)` values in the recorded currency; `PRICE` is
  regular price, `CURRENT_PRICE` is payable price, and `DISCOUNT_PRICE` is null
  without a discount. `DISCOUNT_PERCENT` uses `NUMBER(5, 2)`.
- `OBSERVED_AT` is `TIMESTAMP_TZ`; load the scraper's explicit UTC offset without
  interpreting it in a session-local timezone. Hipermaxi `BATCH` is an integer.
- Raw displayed prices and discount/availability labels are preserved as text.
  A null availability label means unknown, not confirmed in stock.
- `SOURCE_FILE` identifies the staged snapshot path from `METADATA$FILENAME`.
  `SOURCE_ROW_NUMBER` is its one-based data-row position (excluding a CSV
  header). `LOADED_AT` defaults to the warehouse load time.
- CSV, JSONL, and Parquet contain equivalent observations: load only one format
  per run. Parquet currently stores all scraper fields as strings; the
  [Parquet loaders](../../../../../pipelines/ingestion/bronze/load/README.md)
  explicitly convert decimals, timestamps, and batch numbers and preserve nulls.
  No CSV or JSONL loading is implemented.
  Use explicit destination columns rather than relying on positional loading.
- Reject and report malformed or out-of-range conversions; do not use
  conversion-to-null fallbacks, skip invalid rows, or silently round values
  beyond the two-decimal scraper contract. Keep the original snapshots for
  replay and investigation.
- Check `summary.json` and finalized output before loading. Failed/incomplete
  runs require an explicit partial-load decision; preserve run warnings and
  status in the future ingestion workflow. Run summaries are not stored in
  these observation tables.

No primary/unique constraint is declared: standard Snowflake tables do not
enforce those constraints. COPY uses table-specific load history to skip known
files while preserving repeated source observations; this is not permanent
exactly-once protection. See the load guide for retention and replay limitations.
These DDL files alone do not enforce append-only access or replay protection.
