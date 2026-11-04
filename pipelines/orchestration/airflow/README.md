# Airflow orchestration

## Local Docker development

Airflow **3.3.2** is pinned in [compose.yaml](compose.yaml), based on the
current official stable release at setup time. PostgreSQL stores metadata;
LocalExecutor runs tasks without requiring Redis or Celery workers. Separate
API server, scheduler, DAG processor, and triggerer services use the same image.
Allocate at least 4 GB of Docker memory (8 GB recommended).

From the repository root:

Before the first startup, generate a Fernet key with
`docker run --rm --entrypoint python apache/airflow:3.3.2 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`
and save it as `AIRFLOW_FERNET_KEY` in the ignored root `.env`.
Keep this key stable and private: all Airflow services use it to encrypt and
decrypt saved connection credentials. Back it up with the metadata database;
do not replace it without Airflow's supported key-rotation procedure.

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
`AZURE_STORAGE_CONNECTION_STRING`, `AZURE_STORAGE_CONTAINER`, and the optional
`AIRFLOW_CONN_SNOWFLAKE_PHARMA` connection and individual `AIRFLOW_SNOWFLAKE_*` settings are passed to
the scheduler, where scraper tasks run. Keep `.env` out of Git and do not share
these local development credentials.

The existing DAG directory is mounted read-only. DAGs start paused, examples
are disabled, and the scaffold has no schedule and only an empty task.
No jobs run until the manual DAG is triggered. Once triggered, successful
scraper/uploads automatically unlock their corresponding Snowflake loads. The custom image
installs scraper dependencies from the root uv lock into an isolated environment,
plus Chromium and a local browser desktop. Rebuild after source or lock changes.
Airflow runtime dependencies stay isolated from the root uv environment.
The `airflow` dependency group in the root manifest and lock pins Airflow,
its FAB/PostgreSQL support, and the Snowflake provider. The Docker build exports
only that group into Airflow's Python environment; scraper dependencies remain
in `/opt/pharma/.venv`. Update the lock with `uv lock` after manifest changes.
The group also constrains shared libraries to remain compatible with packages
preinstalled in the pinned Airflow image; the build runs `pip check`.

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
uses `pipelines.ingestion.bronze.extract.upload_snapshot`. After updating module
paths, rebuild the image and recreate the scheduler before running the updated
DAG: ingestion code is copied into the image, while DAGs are bind-mounted.
Do not recreate the scheduler during active collection without approval.

The `scrape_pharmacy_prices` DAG has three independent retailer chains (six
tasks), limited to one running task and one active DAG run at a time.
Each scraper task collects all main
categories for its retailer, then uploads only the Parquet file
to the configured Azure Blob Storage container. The blob layout is
`<retailer>/<date>/<filename>`, with `date` taken from the snapshot's UTC run
timestamp and formatted `YYYYMMDD`. CSV, JSONL, and the summary stay local.
The local summary must identify a completed snapshot before upload.
Failed scraper runs are not uploaded. Upload errors fail the
task while retaining its local snapshot. It is manual-only and starts paused.
Each successful scraper/upload task is followed by `load_<retailer>`, which
uses `SQLExecuteQueryOperator` with the Snowflake provider and connection
`snowflake_pharma`. A failed collection/upload prevents only its own load;
other retailer chains remain independent. SQL errors fail the load task.
In the Airflow UI, enable it and trigger a run. Chavez collection proceeds with
a logged snapshot warning if robots rules are missing or return HTML; no
approval parameter is required. Explicit disallow rules and other HTTP errors
still stop collection.

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
No automatic cleanup is configured.

## Configure Snowflake loading

Compose maps `AIRFLOW_SNOWFLAKE_ACCOUNT`, `AIRFLOW_SNOWFLAKE_USER`,
`AIRFLOW_SNOWFLAKE_PASSWORD`, `AIRFLOW_SNOWFLAKE_DATABASE`, `AIRFLOW_SNOWFLAKE_SCHEMA`,
`AIRFLOW_SNOWFLAKE_WAREHOUSE`, `AIRFLOW_SNOWFLAKE_ROLE`, and
`AIRFLOW_SNOWFLAKE_AUTHENTICATOR` from the ignored root `.env` to the scheduler's
corresponding `SNOWFLAKE_*` environment variables. The general `SNOWFLAKE_*`
credentials in `.env` are not passed to the scheduler.
These individual settings are inputs for connection
administration, not an automatic Airflow connection. The `snowflake_pharma`
connection must be saved in Airflow metadata or supplied through the connection
environment variable below. Updating individual settings alone does not update
an already saved connection. Never use `ACCOUNTADMIN` as the loading role.

Before triggering the DAG, create an Airflow connection in **Admin > Connections**:

- Connection ID: `snowflake_pharma`
- Connection type: `Snowflake`
- Account: approved Snowflake account identifier
- Login and authentication: an approved service identity, preferably key-pair
  authentication or your organization's noninteractive authentication method
- Database: `BOLIVIA_PHARMA_PRICE_ENGINE`
- Schema: `BRONZE`
- Warehouse and role: explicitly approved loading warehouse and least-privileged
  ingestion role (the governance SQL proposes `COMPUTE_WH` and
  `PHARMA_DEV_INGESTOR`; confirm their deployment and access before using them)

Use the connection's Extra fields for `account`, `database`, `warehouse`, `role`,
and any required authentication settings. For key-pair authentication the provider
supports `private_key_content` or `private_key_file` (not both); a file must be
securely mounted and readable by the actual task runtime. Enter secrets only
through approved Airflow connection/secret management, never in the DAG or Git.
Do not use interactive browser authentication for unattended tasks.
See the [provider connection documentation](https://airflow.apache.org/docs/apache-airflow-providers-snowflake/stable/connections/snowflake.html).

Connections saved in the UI persist in Airflow's metadata database. An approved
secrets backend can supply the same connection ID instead. No connection or
credentials are created by this code. Alternatively, set
`AIRFLOW_CONN_SNOWFLAKE_PHARMA` in the ignored root `.env` to an Airflow JSON
connection; Compose passes only this optional Snowflake setting to the scheduler,
where LocalExecutor tasks run. Environment connections do not appear in the UI
connection list. For example, replace the authentication placeholders locally:

```dotenv
AIRFLOW_CONN_SNOWFLAKE_PHARMA='{"conn_type":"snowflake","login":"<service-user>","password":"<secret>","schema":"BRONZE","extra":{"account":"<approved-account>","database":"BOLIVIA_PHARMA_PRICE_ENGINE","warehouse":"COMPUTE_WH","role":"PHARMA_DEV_INGESTOR"}}'
```

Use the provider's key-pair fields in `extra` instead when applicable; never
commit the rendered connection. Recreate the scheduler after changing this
environment setting, only when no tasks are running or interruption is approved.
Compose requires the shared `AIRFLOW_FERNET_KEY` described above.
For shared/production use, configure your secret-management policy separately;
the local Compose setup is not
a production credential store.

The load SQL files are packaged at `/opt/pharma/pipelines/ingestion/bronze/load`;
the DAG uses that template search path. Rebuild the image and recreate Airflow
services, including the DAG processor and scheduler, for provider/SQL changes.
Simply updating the bind-mounted DAG against an old image is insufficient.

The existing [load guide](../../ingestion/bronze/load/README.md) defines required
stages, tables, integration permissions, and replay limits. Operators do not
create or alter those objects. Each COPY loads all matching date folders for its
retailer, not just the snapshot from the current DAG run, and skips known files
according to Snowflake load history. It preserves blobs and raw duplicate rows.
A no-new-files result can be successful; it is not a freshness assertion.
No COPY results are pushed into XCom.

To retry a failed load without scraping again, clear only its `load_<retailer>`
task after resolving the error; leave the successful scraper task untouched.
No automatic task retries are configured.

Offline container checks (no pharmacy requests):

```bash
docker compose --env-file .env -f pipelines/orchestration/airflow/compose.yaml cp pipelines/orchestration/airflow/tests/test_scraper_dag.py airflow-scheduler:/tmp/test_scraper_dag.py
docker compose --env-file .env -f pipelines/orchestration/airflow/compose.yaml exec -T airflow-scheduler python /tmp/test_scraper_dag.py
```

Offline SQL-operator checks (mocked hooks, no Snowflake connection):

```bash
docker compose --env-file .env -f pipelines/orchestration/airflow/compose.yaml run --rm --no-deps -v "$PWD/pipelines/orchestration/airflow/tests:/tmp/dag-tests:ro" --entrypoint python airflow-scheduler -m unittest discover -s /tmp/dag-tests -p 'test_snowflake_loading.py' -v
```
