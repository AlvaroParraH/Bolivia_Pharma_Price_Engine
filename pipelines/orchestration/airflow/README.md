# Airflow orchestration

`dags/scaffold_pipeline.py` contains a single empty task. It performs no
Snowflake or data operations. Confirm the Airflow runtime, provider versions,
approved authentication, schedule/timezone, and release process before
extending or deploying it.

Do not put credentials or rendered connection profiles in this repository.
