# dbt project

The dbt project name is `bolivia_pharma_price_engine`. The starter model at
`models/silver/staging/scaffold_example.sql` is a deterministic zero-row
example and reads no project data. Replace it before selecting it in a real
build. A dbt run can create or change Snowflake objects.

dbt Core and the Snowflake adapter are installed through the root manifest's
`dbt` dependency group and pinned by the root `uv.lock`. The adapter is pinned
to `dbt-snowflake==1.12.5`. From the repository root:

```bash
uv sync --locked --group dbt
uv run --no-env-file --locked --group dbt dbt --version
```

This group is separate from Airflow's runtime group and is not installed in
the Airflow Docker image. No `profiles.yml` or dbt package configuration is
generated. Configure an approved local profile outside Git, authentication,
target environment, object ownership, and deployment workflow before running
models. Installation and version checks do not connect to Snowflake.

## Model areas

- `models/silver/staging/`
- `models/silver/intermediate/`
- `models/gold/marts/`
- `tests/` - dbt tests, separate from the root Python test directory.
- `macros/` - reusable SQL macros when needed.
- `snapshots/` - approved history capture when needed.
