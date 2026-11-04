# Bronze stage migrations

Place reviewed SQL changes for stages in the Bronze schema here. No migration
runner or execution order is configured yet.

[scraped_prices_stages.sql](scraped_prices_stages.sql) defines three external
Parquet stages in `BOLIVIA_PHARMA_PRICE_ENGINE.BRONZE`, one per retailer.
Each references `AZURE_BOLIVIA_PHARMA_BRONZE` and the corresponding
`<retailer>/` Azure prefix, including all UTC run-date subfolders.
These definitions match the current uploader. Stages with different deployed
URLs require a separately
reviewed and approved URL change, not automatic recreation.
These stage definitions have not been executed.

Create the [shared Parquet file format](../file_formats/README.md) before these
stages. All three stages reference it by fully qualified name; the COPY scripts
inherit the stage format rather than supplying inline parsing options.

Before deployment, confirm the account, database, Bronze schema, integration,
and Azure consent/RBAC. The creating role needs parent `USAGE`, schema
`CREATE STAGE`, and integration `USAGE`. Use the approved deployer role after
its grants are applied. Plain `CREATE STAGE` fails on existing objects without
replacing them. Statements commit independently; inspect partial deployment
before retrying.

Stage creation does not load or transform data. The separate
[Bronze load scripts](../../../../../pipelines/ingestion/bronze/load/README.md)
perform typed `COPY INTO` loads. Apply the
[ingestor grants](../../../governance/grants/pharma_dev_ingestor.sql) after
stages and target tables exist. No grants or uploads run automatically.
