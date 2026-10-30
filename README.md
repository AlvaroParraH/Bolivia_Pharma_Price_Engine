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

Before implementing collection, review each site's terms and robots policy,
prefer an approved data access method, and use conservative request rates.
Record observation dates and source provenance; do not bypass access controls.

## Project layout

- `pipelines/ingestion/bronze/` - source extraction and raw ingestion.
- `pipelines/dbt/` - Silver transformations and Gold marts.
- `pipelines/orchestration/airflow/dags/` - orchestration.
- `tests/` - local Python test guidance.
- `docs/project-profile.md` - reviewed project context.

## Local Python and Playwright setup

Use Python 3.11 or newer with uv. Playwright is the selected browser automation
library for the initial Farmacorp work. The category collector is implemented;
scheduled collection and Snowflake loading are not configured.

From the project root:

```bash
uv sync --locked
uv run --no-env-file --locked playwright install chromium
```

Dependencies are recorded in `pyproject.toml` and resolved in `uv.lock`.
Playwright stores its downloaded browsers in the user's browser cache, outside
the repository. Re-run the browser installation after upgrading Playwright.
The `--no-env-file` option avoids loading local environment files; the browser
setup requires no credentials.

## Collect Farmacorp prices

Start with all pages in Ofertas:

```bash
uv run --no-env-file --locked python -m pipelines.ingestion.bronze.scrape_farmacorp
```

Timestamped JSONL/CSV/Parquet snapshots and a completion summary are saved under
`data/farmacorp/`, outside source control. See the
[Bronze collection guide](pipelines/ingestion/bronze/README.md) for field meanings,
other categories, validation, and responsible collection limits.

To collect the other main categories into a new filterable CSV/JSONL/Parquet snapshot:

```bash
uv run --no-env-file --locked python -m pipelines.ingestion.bronze.scrape_farmacorp --main-categories --exclude-category ofertas
```

Every row includes `category` and `category_url`. Existing Ofertas snapshots
are preserved; nested subcategories are not separately crawled in this mode.

## Collect Farmacias Chavez prices

```bash
uv run --no-env-file --locked python -m pipelines.ingestion.bronze.scrape_farmacias_chavez --allow-missing-robots
```

Collects paginated main-menu categories into timestamped CSV/JSONL/Parquet
snapshots under `data/farmacias_chavez/`. The explicit flag approves proceeding
when the site's robots endpoint is missing or returns HTML. See the
[Bronze collection guide](pipelines/ingestion/bronze/README.md) for policy
uncertainty, category filtering, price semantics, and location limitations.

## Collect Hipermaxi prices

A collector is available in
[`scrape_hipermaxi.py`](pipelines/ingestion/bronze/scrape_hipermaxi.py).
It targets La Paz / Farmacia Calacoto, main categories and infinite scrolling,
with matching timestamped CSV/JSONL/Parquet output. The first full collection
completed all 14 main categories with 4,366 unique products, including 318 with
discounts, across 96 scroll batches. All three output formats were verified.
Initial pilots encountered validation and a subsequently fixed category-readiness
bug; future access is not guaranteed. No automatic validation bypass is used. See the
[Bronze guide](pipelines/ingestion/bronze/README.md) for details.

For approved collection with manual validation, opt into a visible browser:

```bash
uv run --no-env-file --locked python -m pipelines.ingestion.bronze.scrape_hipermaxi --interactive
```

If redirected to Radware, collection pauses for up to five minutes for you to
interact in that window. It resumes only after returning to Calacoto in the
same session. No challenge is solved automatically. Headless mode still stops
on validation. This workflow does not guarantee access or grant permission.
Add `--category farmacia-genericos` to limit collection to that category.

## Before implementation

Confirm existing project conventions, data classification, source access,
object ownership, environment boundaries, and deployment workflow. Replace
each clearly marked placeholder before using it.

The generic ingestion placeholder, dbt, and Airflow files remain starter
templates. The local Playwright setup does not create connection profiles or
credentials, connect to Snowflake, execute dbt, or deploy Airflow. Running dbt
after configuring an approved profile can create Snowflake objects.
