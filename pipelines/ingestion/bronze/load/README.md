# Azure to Snowflake Bronze loads

These are local SQL files, not a deployed or automatically scheduled loader.
They use the retailer table, stage, integration, and shared Parquet file-format
contracts. The Azure uploader lives in `../extract/`.

| Load | Existing target in `BOLIVIA_PHARMA_PRICE_ENGINE.BRONZE` | Stage in the same schema |
|---|---|---|
| [Farmacorp](load_farmacorp.sql) | `SCRAPED_FARMACORP_PRICES` | `FARMACORP_SCRAPED_PRICES_STAGE` |
| [Farmacias Chavez](load_farmacias_chavez.sql) | `SCRAPED_FARMACIAS_CHAVEZ_PRICES` | `FARMACIAS_CHAVEZ_SCRAPED_PRICES_STAGE` |
| [Hipermaxi](load_hipermaxi.sql) | `SCRAPED_HIPERMAXI_PRICES` | `HIPERMAXI_SCRAPED_PRICES_STAGE` |

## Prerequisites and review order

1. Confirm the approved account/environment, role, warehouse, database, and
   schema before execution. Nothing here creates a database, schema, role,
   warehouse, integration, or grants.
2. Reuse the existing account-level storage integration
   `AZURE_BOLIVIA_PHARMA_BRONZE`. Do not recreate it or repeat Azure consent.
   Its existence, enabled state, allowed locations, Azure authorization, and
   privileges have not been verified in this change.
3. Review the [table definitions](../../../../infra/snowflake/migrations/bronze/tables/)
   and [shared Parquet format](../../../../infra/snowflake/migrations/bronze/file_formats/parquet_snapshots_format.sql).
   Create only missing, approved objects; the SQL deliberately uses plain
   `CREATE`, not `CREATE OR REPLACE` or `IF NOT EXISTS` that could hide drift.
   Existing tables must match the column types and required/default columns.
4. Review the [stage definitions](../../../../infra/snowflake/migrations/bronze/stages/scraped_prices_stages.sql).
   They reference the existing integration and named Parquet format.
   Uploads use `<retailer>/YYYYMMDD/<filename>.parquet` directly inside the
   container. These definitions reflect the current layout. If a stage already
   exists with a different URL, stop and obtain approval for its exact `ALTER STAGE`
   change; rerunning `CREATE` will not update it.
5. Confirm the configured Azure container/account matches the stage
   URLs. The uploader's environment configuration has not been inspected.
   The loading role needs warehouse/database/schema access, `INSERT` on the
   target, `USAGE` on the external stage and file format, and the stage owner
   needs the appropriate integration privileges. Have the administrator review
   existing grants; these files grant nothing.

After those checks, execute the corresponding load SQL through the approved
Snowflake client with the approved role and warehouse. This change intentionally
does not add an executor, Snowflake dependency, or Airflow loading task.

## Load and replay behavior

- Each statement scans matching Parquet snapshots across all date folders in
  its retailer stage. The filename pattern also accommodates the full storage
  path used by bulk COPY. CSV, JSONL, and summaries do not match.
- Explicit mappings retain every scraper field, using the earlier typed Bronze
  contract: decimal prices, timestamp observations, and a numeric Hipermaxi batch.
  Raw displayed price strings remain available. No joins, business corrections,
  or deduplication are applied; repeated observations from retries stay in Bronze.
- `SOURCE_FILE` and `SOURCE_ROW_NUMBER` preserve staged-file provenance.
  `LOADED_AT` defaults to the Snowflake load time, not the observation time.
- `ON_ERROR = ABORT_STATEMENT` fails the retailer load on conversion errors
  instead of silently skipping invalid rows. The three loads are independent;
  success for one does not mean success for the others.
- `FORCE = FALSE` uses Snowflake's table-specific load metadata to skip known
  files; `LOAD_UNCERTAIN_FILES = FALSE` avoids automatically loading older files
  whose status is uncertain. This is **not permanent exactly-once protection**:
  metadata retention is bounded, recreated tables lose load history, and renamed
  files can be treated as new files. Review backfills explicitly.
- `PURGE = FALSE` preserves source blobs. Do not truncate tables, force reloads,
  or change filenames as an automatic retry strategy.
- Inspect each COPY result for file statuses, parsed/loaded row counts, and
  errors. A successful command with no new files is not proof of fresh data;
  reconcile the expected uploaded files before declaring the batch complete.

Offline tests check field/type mappings, table alignment, upload-path matching,
and load options. They do not prove Snowflake acceptance, access, live object
state, or successful loading. SQLFluff is not currently installed in the project,
so parser/lint validation requires separately approved tooling.

Reference: [Snowflake COPY INTO table](https://docs.snowflake.com/en/sql-reference/sql/copy-into-table).
