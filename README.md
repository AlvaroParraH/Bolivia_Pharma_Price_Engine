# bolivia_pharma_price_engine

Track and compare pharmacy product prices in Bolivia month to month, identify
price increases and decreases, and analyze how price movements relate to
changes in the US dollar to Bolivian boliviano exchange rate.

## Project context

- **Domain:** Bolivian pharmacy retail pricing and price trends.
- **Owner/team:** Not provided.
- **Data sensitivity:** public
- **Primary consumers:** Twitter X
- **Initial environment:** dev
- **Primary source:** multiple source types

## Initial data sources and analysis

The initial pharmacy sources are:

- [Farmacorp](https://farmacorp.com/)
- [Farmacias Chávez](https://www.farmaciaschavez.com.bo/)
- [Hipermaxi Farmacia Calacoto](https://www.hipermaxi.com/la-paz/farmacia-calacoto)

The planned analysis compares product prices across monthly observations and
classifies observed changes as increases or decreases. It will also compare
those changes with the USD/BOB exchange rate. The exchange-rate data source,
product matching rules across pharmacies, and price observation schedule are
not yet selected.

Collection uses public catalog pages, conservative request pacing, and
source-specific robots checks. Observation dates and source provenance are
preserved. Access challenges are not bypassed automatically.

## Architecture

```text
Pharmacy websites
    |
    v
Playwright scrapers -> Local CSV / JSONL / Parquet snapshots
    |
    v
Azure Blob Storage (Parquet only: <retailer>/YYYYMMDD/<filename>)
    |
    v
Snowflake Bronze -> dbt Silver -> dbt Gold
```

- **Extraction:** retailer-specific collectors preserve prices, categories,
  observation timestamps, and raw displayed values. Bounded category timeout
  retries retain partial observations, including duplicates.
- **Orchestration:** a manual Airflow DAG runs the three retailer collections
  independently, one at a time, and uploads completed Parquet snapshots.
- **Bronze:** SQL COPY scripts map staged Parquet files into retailer-specific
  Snowflake tables with file provenance. Loading is not yet wired into Airflow;
  the SQL definitions do not establish live deployment state.
- **Silver (planned):** dbt models will normalize types, validate data, and
  deduplicate observations at an agreed grain while preserving price history.
- **Gold (planned):** business-facing models will support monthly price changes,
  retailer comparisons, and exchange-rate analysis.
- **Governance:** separate SQL definitions describe roles, grants, the Azure
  storage integration, and warehouse objects. Runtime and provisioning
  responsibilities remain separate.

## Project layout

- `pipelines/ingestion/bronze/` - `extract/` for source collection and local
  snapshots and Azure publication; `load/` contains reviewed-before-use Snowflake
  COPY scripts (not yet deployed or wired into Airflow).
- `pipelines/dbt/` - Silver transformations and Gold marts.
- `pipelines/orchestration/airflow/dags/` - orchestration.
- `infra/snowflake/` - governance and warehouse object definitions.
- `tests/` - offline Python tests and validation guidance.
- `docs/project-profile.md` - reviewed project context.

## Documentation

- [Setup and operating instructions](docs/local-development.md)
- [Collection contracts and limitations](pipelines/ingestion/bronze/README.md)
- [Snowflake loading design and prerequisites](pipelines/ingestion/bronze/load/README.md)
- [Airflow runtime guide](pipelines/orchestration/airflow/README.md)
- [Test guide](tests/README.md)
