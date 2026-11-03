"""Manually collect pharmacy catalogs and upload completed snapshots to Azure."""

from datetime import timedelta

import pendulum
from airflow.sdk import DAG, Param
from airflow.providers.standard.operators.bash import BashOperator

with DAG(
    dag_id="scrape_pharmacy_prices",
    start_date=pendulum.datetime(2026, 1, 1, tz="America/La_Paz"),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    max_active_tasks=1,
    default_args={"retries": 0, "execution_timeout": timedelta(hours=12)},
    params={
        "allow_missing_chavez_robots": Param(
            False,
            type="boolean",
            description="Explicitly approve Chavez collection if robots.txt is missing/HTML.",
        ),
    },
    doc_md=(
        "Collects all main categories, retains local snapshots, and uploads completed snapshots to Azure Blob Storage. "
        "Tasks run one at a time but independently, so one failure does not skip other retailers. "
        "Open http://localhost:6080/vnc.html for Hipermaxi manual validation (300 seconds "
        "per challenge). No challenge bypass, automatic retries, or Snowflake calls."
    ),
    tags=["bronze", "scraping", "manual"],
) as dag:
    scrape_farmacorp = BashOperator(
        task_id="scrape_farmacorp",
        bash_command="""set -euo pipefail
mkdir -p /opt/airflow/snapshots/farmacorp
snapshot_root="$(mktemp -d /opt/airflow/snapshots/farmacorp/airflow-run-XXXXXX)"
/opt/pharma/.venv/bin/python -u -m pipelines.ingestion.bronze.extract.scrape_farmacorp --main-categories --output "$snapshot_root"
/opt/pharma/.venv/bin/python -u -m pipelines.ingestion.bronze.load.upload_snapshot --snapshot-root "$snapshot_root" --retailer farmacorp""",
        cwd="/opt/pharma",
        env={"DISPLAY": "browser-desktop:99"},
        append_env=True,
        do_xcom_push=False,
    )

    scrape_farmacias_chavez = BashOperator(
        task_id="scrape_farmacias_chavez",
        bash_command="""set -euo pipefail
mkdir -p /opt/airflow/snapshots/farmacias_chavez
snapshot_root="$(mktemp -d /opt/airflow/snapshots/farmacias_chavez/airflow-run-XXXXXX)"
/opt/pharma/.venv/bin/python -u -m pipelines.ingestion.bronze.extract.scrape_farmacias_chavez {% if params.allow_missing_chavez_robots %}--allow-missing-robots{% endif %} --output "$snapshot_root"
/opt/pharma/.venv/bin/python -u -m pipelines.ingestion.bronze.load.upload_snapshot --snapshot-root "$snapshot_root" --retailer farmacias_chavez""",
        cwd="/opt/pharma",
        env={"DISPLAY": "browser-desktop:99"},
        append_env=True,
        do_xcom_push=False,
    )

    scrape_hipermaxi = BashOperator(
        task_id="scrape_hipermaxi",
        bash_command="""set -euo pipefail
mkdir -p /opt/airflow/snapshots/hipermaxi
snapshot_root="$(mktemp -d /opt/airflow/snapshots/hipermaxi/airflow-run-XXXXXX)"
/opt/pharma/.venv/bin/python -u -m pipelines.ingestion.bronze.extract.scrape_hipermaxi --interactive --validation-timeout 300 --output "$snapshot_root"
/opt/pharma/.venv/bin/python -u -m pipelines.ingestion.bronze.load.upload_snapshot --snapshot-root "$snapshot_root" --retailer hipermaxi""",
        cwd="/opt/pharma",
        env={"DISPLAY": "browser-desktop:99"},
        append_env=True,
        do_xcom_push=False,
    )
