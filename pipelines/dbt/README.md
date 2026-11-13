# dbt project

The dbt project name is `bolivia_pharma_price_engine`. The starter model at
`models/silver/staging/scaffold_example.sql` is a deterministic zero-row
example and reads no project data. Replace it before selecting it in a real
build. A dbt run can create or change Snowflake objects.

dbt Core and the Snowflake adapter are installed through the root manifest's
`dbt` dependency group and pinned by the root `uv.lock`. The adapter is pinned
to `dbt-snowflake==1.12.5`. From the repository root:

```bash
uv sync --locked --group dbt
uv run --no-env-file --locked --group dbt dbt --version
```

This group is separate from Airflow's runtime group and is not installed in
the Airflow Docker image. No `profiles.yml` or dbt package configuration is
generated. Configure an approved local profile outside Git, authentication,
target environment, object ownership, and deployment workflow before running
models. Installation and version checks do not connect to Snowflake.

## Model areas

- `seeds/` - reviewed static reference CSVs loaded into the configured target
  schema. Set the profile target schema to
  `BOLIVIA_PHARMA_PRICE_ENGINE.SILVER` before running
  `dbt seed --select product_categories` to create
  `PRODUCT_CATEGORIES`. Use `--full-refresh` only after inspecting the existing
  seed table; it rebuilds the table and can replace its contents.
- `models/silver/staging/`
- `models/silver/intermediate/`
- `models/gold/marts/`
- `tests/` - dbt tests, separate from the root Python test directory.
- `macros/` - reusable SQL macros when needed.
- `snapshots/` - approved history capture when needed.

The three `models/silver/staging/stg_*__prices.sql` models select the Bronze
observations without deduplicating products, so repeated product observations
remain available for later Silver analysis. They use `LOADED_AT` (the
Snowflake ingestion timestamp) as the incremental boundary: the first run
selects all history, and later runs reprocess from one calendar day before the
latest loaded date already in each target. `SOURCE_FILE` plus
`SOURCE_ROW_NUMBER` is the merge key, making reruns idempotent for a landed
source row while retaining separate source rows for the same product.

The one-day lookback only captures late-arriving rows within that window; older
backfills require a reviewed full refresh or another explicit backfill
approach. Correct incremental merges depend on the source-file and row-number
combination being unique for each retailer. Schema changes fail by default and
require an explicit review. These models have not been run against Snowflake;
configure and verify the intended profile and target before executing dbt.

The Silver intermediate `int_products__identity` view combines the three
staging models. Its product key is the pair `RETAILER` and
`RETAILER_PRODUCT_ID`: the latter is Farmacorp's product handle or the product
ID for Farmacias Chavez and Hipermaxi. Whitespace-only key components are
treated as missing. Identified products use their latest observed row, with
load time and source provenance breaking ties. Rows with missing key
components remain visible as `unresolved` and are not matched by URL or name.
The source category remains in staging; this model neither assigns canonical
categories nor matches products across retailers. Brand is available only
where the source supplies it.

Retailer IDs and Farmacorp handles are candidate identities, not guaranteed
permanent identifiers. Review changes and collisions over time before using
them for durable classifications. The latest row can change when older source
files are backfilled into staging or source attributes change. This view has
not been run against Snowflake.
