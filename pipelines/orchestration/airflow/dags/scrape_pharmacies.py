"""Collect pharmacy catalogs, publish Parquet, and load Snowflake Bronze."""

from datetime import timedelta

import pendulum
from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator
from airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator

with DAG(
    dag_id="scrape_pharmacy_prices",
    start_date=pendulum.datetime(2026, 1, 1, tz="America/La_Paz"),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    max_active_tasks=1,
    template_searchpath=["/opt/pharma/pipelines/ingestion/bronze/load"],
    default_args={"retries": 0, "execution_timeout": timedelta(hours=12)},
    doc_md=(
        "Collects all main categories, retains local snapshots, and uploads completed snapshots to Azure Blob Storage. "
        "Each successful scraper/upload is followed by its Snowflake Bronze COPY load "
        "using connection snowflake_pharma. Retailer chains are independent and tasks run one at a time. "
        "Open http://localhost:6080/vnc.html for Hipermaxi manual validation (300 seconds "
        "per challenge). No challenge bypass or automatic task retries. "
        "COPY loads matching date folders, skips known files, and preserves source blobs."
    ),
    tags=["bronze", "scraping", "manual"],
) as dag:
    scrape_farmacorp = BashOperator(
        task_id="scrape_farmacorp",
        bash_command="""set -euo pipefail
mkdir -p /opt/airflow/snapshots/farmacorp
snapshot_root="$(mktemp -d /opt/airflow/snapshots/farmacorp/airflow-run-XXXXXX)"
/opt/pharma/.venv/bin/python -u -m pipelines.ingestion.bronze.extract.scrape_farmacorp --main-categories --output "$snapshot_root"
/opt/pharma/.venv/bin/python -u -m pipelines.ingestion.bronze.extract.upload_snapshot --snapshot-root "$snapshot_root" --retailer farmacorp""",
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
/opt/pharma/.venv/bin/python -u -m pipelines.ingestion.bronze.extract.scrape_farmacias_chavez --output "$snapshot_root"
/opt/pharma/.venv/bin/python -u -m pipelines.ingestion.bronze.extract.upload_snapshot --snapshot-root "$snapshot_root" --retailer farmacias_chavez""",
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
/opt/pharma/.venv/bin/python -u -m pipelines.ingestion.bronze.extract.upload_snapshot --snapshot-root "$snapshot_root" --retailer hipermaxi""",
        cwd="/opt/pharma",
        env={"DISPLAY": "browser-desktop:99"},
        append_env=True,
        do_xcom_push=False,
    )

    for retailer, scrape_task in (
        ("farmacorp", scrape_farmacorp),
        ("farmacias_chavez", scrape_farmacias_chavez),
        ("hipermaxi", scrape_hipermaxi),
    ):
        load_task = SQLExecuteQueryOperator(
            task_id=f"load_{retailer}",
            conn_id="snowflake_pharma",
            sql=f"load_{retailer}.sql",
            autocommit=True,
            split_statements=False,
            do_xcom_push=False,
            handler=None,
            execution_timeout=timedelta(hours=1),
        )
        scrape_task >> load_task
