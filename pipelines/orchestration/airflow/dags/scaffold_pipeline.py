"""Empty Airflow DAG starter for bolivia_pharma_price_engine; no Snowflake work is performed."""

import pendulum
from airflow import DAG
from airflow.operators.empty import EmptyOperator


with DAG(
    dag_id="bolivia_pharma_price_engine_pipeline",
    start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
    schedule=None,
    catchup=False,
    doc_md="Replace the empty task with reviewed project orchestration.",
) as dag:
    placeholder = EmptyOperator(task_id="replace_with_project_tasks")
