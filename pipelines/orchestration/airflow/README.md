# Airflow orchestration

## Local Docker development

Airflow **3.3.2** is pinned in [compose.yaml](compose.yaml), based on the
current official stable release at setup time. PostgreSQL stores metadata;
LocalExecutor runs tasks without requiring Redis or Celery workers. Separate
API server, scheduler, DAG processor, and triggerer services use the same image.
Allocate at least 4 GB of Docker memory (8 GB recommended).

From the repository root:

```bash
docker compose --env-file .env -f pipelines/orchestration/airflow/compose.yaml up -d --build --wait --wait-timeout 300
docker compose --env-file .env -f pipelines/orchestration/airflow/compose.yaml ps
```

Open http://localhost:8080 and sign in with `airflow` / `airflow`.
These public development-only credentials and the local JWT secret are not
suitable for production or shared hosting. The API server and browser desktop
are published only on loopback; PostgreSQL is not exposed to the host.
The init service migrates the metadata database and creates the local user.
The root `.env` is used for Compose interpolation; it is not mounted. Only
`AZURE_STORAGE_CONNECTION_STRING` and `AZURE_STORAGE_CONTAINER` are passed to
the scheduler, where scraper tasks run. Keep `.env` out of Git and do not share
these local development credentials.

The existing DAG directory is mounted read-only. DAGs start paused, examples
are disabled, and the scaffold has no schedule and only an empty task.
No scraping, upload, or Snowflake jobs run automatically. The custom image
installs scraper dependencies from the root uv lock into an isolated environment,
plus Chromium and a local browser desktop. Rebuild after source or lock changes.
Airflow runtime dependencies stay isolated from the root uv environment.

```bash
# Diagnose services
docker compose --env-file .env -f pipelines/orchestration/airflow/compose.yaml logs --tail 100 airflow-scheduler airflow-dag-processor
# Stop without deleting metadata or logs
docker compose --env-file .env -f pipelines/orchestration/airflow/compose.yaml down
```

Named volumes retain metadata and logs across restarts. Do not remove volumes
unless intentionally resetting the development instance. This Compose project
is a local development setup, not a production deployment.

`dags/scaffold_pipeline.py` contains a single empty task. It performs no
Snowflake or data operations. Confirm the Airflow runtime, provider versions,
approved authentication, schedule/timezone, and release process before
extending or deploying it.

Do not put credentials or rendered connection profiles in this repository.

## Run the three scrapers

Scraper modules live under `pipelines.ingestion.bronze.extract`; Azure publication
uses `pipelines.ingestion.bronze.load.upload_snapshot`. After updating module
paths, rebuild the image and recreate the scheduler before running the updated
DAG: ingestion code is copied into the image, while DAGs are bind-mounted.
Do not recreate the scheduler during active collection without approval.

The `scrape_pharmacy_prices` DAG has three independent tasks, limited to one
running task and one active DAG run at a time. Each task collects all main
categories for its retailer, then uploads only the Parquet file
to the configured Azure Blob Storage container. The blob layout is
`<retailer>/<date>/<filename>`, with `date` taken from the snapshot's UTC run
timestamp and formatted `YYYYMMDD`. CSV, JSONL, and the summary stay local.
The local summary must identify a completed snapshot before upload.
Failed scraper runs are not uploaded. Upload errors fail the
task while retaining its local snapshot. It is manual-only and starts paused.
In the Airflow UI, enable it and trigger a run. Explicitly select
`allow_missing_chavez_robots` if you approve collection despite missing/HTML
robots rules; otherwise the Chavez scraper stops if usable rules are absent.

Before triggering, open http://localhost:6080/vnc.html and click **Connect**.
The Hipermaxi task includes all discovered main categories, including
`No Comestible` (`no-comestible`); no category exclusions are configured.
Hipermaxi launches visible Chromium there. Watch its task logs and interact
manually if site validation appears; each challenge has a 300-second timeout.
No challenge solving, access bypass, or session reuse is automated. The browser
desktop has no password and is bound to localhost; do not expose it or the
internal Docker display port to untrusted networks.

Scraper subprocess failures fail their tasks, retain partial files, and do not
skip the other pharmacies. There are no automatic task retries to avoid replaying
collections. All three scrapers separately retry a timed-out category up to twice,
waiting at least 10 seconds plus jitter, retaining earlier raw rows, and recording
attempts in the local summary. Recovery completes with warnings; a third timeout
fails the snapshot and prevents upload. Non-timeout errors are not retried.
Clearing/re-running a task creates a new snapshot, not a resume.
Observe existing request pacing and site policy; no live collection is performed
as part of deployment validation.

CSV, JSONL, Parquet, and summaries persist in the `airflow-snapshots` named
volume at `/opt/airflow/snapshots/<retailer>/airflow-run-<random>/<run_id>/`.
To export them:

```bash
mkdir -p data/airflow-snapshots
docker compose --env-file .env -f pipelines/orchestration/airflow/compose.yaml cp airflow-scheduler:/opt/airflow/snapshots/. data/airflow-snapshots/
```

Snapshots survive `down` but not deliberate volume deletion. Only the finalized
Parquet blob is published; there is no remote summary completion marker.
Existing CSV, JSONL, or summary blobs from earlier uploads are not deleted.
No automatic cleanup or Snowflake load is configured.

Offline container checks (no pharmacy requests):

```bash
docker compose --env-file .env -f pipelines/orchestration/airflow/compose.yaml cp pipelines/orchestration/airflow/tests/test_scraper_dag.py airflow-scheduler:/tmp/test_scraper_dag.py
docker compose --env-file .env -f pipelines/orchestration/airflow/compose.yaml exec -T airflow-scheduler python /tmp/test_scraper_dag.py
```
