# Setup and operating instructions

See the [main README](../README.md) for project design and architecture.
Run the following commands from the project root.

## Local Python and Playwright setup

Use Python 3.11 or newer with uv. Playwright and Chromium provide browser
automation for all three retailer collectors.

```bash
uv sync --locked
uv run --no-env-file --locked playwright install chromium
```

Dependencies are recorded in `pyproject.toml` and resolved in `uv.lock`.
Playwright stores its downloaded browsers in the user's browser cache, outside
the repository. Re-run the browser installation after upgrading Playwright.
The `--no-env-file` option avoids loading local environment files; browser
setup requires no credentials.

## Before collecting

Review each site's terms and robots policy, use approved access, and preserve
the configured request pacing. Do not bypass access controls.
Local snapshots stay outside source control under `data/<retailer>/`.
Each run writes timestamped CSV, JSONL, Parquet, and a completion summary.
Check the summary status before consuming partial output.

## Collect Farmacorp prices

Start with all pages in Ofertas:

```bash
uv run --no-env-file --locked python -m pipelines.ingestion.bronze.extract.scrape_farmacorp
```

To collect the other main categories into a new snapshot:

```bash
uv run --no-env-file --locked python -m pipelines.ingestion.bronze.extract.scrape_farmacorp --main-categories --exclude-category ofertas
```

Every row includes `category` and `category_url`. Existing Ofertas snapshots
are preserved; nested subcategories are not separately crawled in this mode.
Output defaults to `data/farmacorp/`.

## Collect Farmacias Chavez prices

```bash
uv run --no-env-file --locked python -m pipelines.ingestion.bronze.extract.scrape_farmacias_chavez
```

The explicit flag approves proceeding when the site's robots endpoint is
missing or returns HTML. Omit it unless that access decision is approved.
The collector traverses paginated main-menu categories without selecting a
delivery location. Output defaults to `data/farmacias_chavez/`.

## Collect Hipermaxi prices

The collector targets La Paz / Farmacia Calacoto and uses main categories
with infinite scrolling. For approved collection with manual validation,
opt into a visible browser:

```bash
uv run --no-env-file --locked python -m pipelines.ingestion.bronze.extract.scrape_hipermaxi --interactive
```

If redirected to Radware, collection pauses for up to five minutes for you to
interact in that window. It resumes only after returning to Calacoto in the
same session. No challenge is solved automatically. Headless mode stops on
validation. This workflow does not guarantee access or grant permission.
Add `--category farmacia-genericos` to limit the scope.
Output defaults to `data/hipermaxi/`.

See the [Bronze collection guide](../pipelines/ingestion/bronze/README.md)
for field meanings, retry behavior, filtering, and source limitations.

## Run offline tests

```bash
uv run --no-env-file --locked python -m unittest discover -s tests -p 'test_*.py' -q
```

See the [test guide](../tests/README.md) for focused suites and coverage.
These tests do not establish live site access or Snowflake deployment state.

## Run Airflow and publish to Azure

Follow the [Airflow runtime guide](../pipelines/orchestration/airflow/README.md)
for Docker setup, local UI access, manual DAG runs, Azure configuration, and
visible-browser interaction. The DAG uploads only completed Parquet snapshots.
Rebuild the image and recreate the scheduler after ingestion code changes;
do not interrupt active collections without approval.

## Load Snowflake Bronze tables

Follow the [Snowflake load guide](../pipelines/ingestion/bronze/load/README.md)
for stage paths, object prerequisites, permissions, COPY scripts, and replay
limitations. Configure Airflow's `snowflake_pharma` connection before triggering
the scraper DAG, which loads each retailer after successful upload.
Confirm the exact approved
target and operation before executing warehouse SQL.

## Development and deployment boundaries

Keep credentials and rendered connection profiles out of source control.
Local Python setup does not create credentials or connection profiles,
connect to Snowflake, execute dbt, or deploy Airflow.
The dbt project still contains starter models; running dbt with a configured
profile can connect to Snowflake and create objects. Review source contracts,
ownership, environment boundaries, and deployment approval before extending
or running warehouse workflows.
