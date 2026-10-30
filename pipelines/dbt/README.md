# dbt project

The dbt project name is `bolivia_pharma_price_engine`. The starter model at
`models/silver/staging/scaffold_example.sql` is a deterministic zero-row
example and reads no project data. Replace it before selecting it in a real
build. A dbt run can create or change Snowflake objects.

No `profiles.yml`, adapter dependency, package, or lockfile is generated.
Confirm the dbt version, Snowflake adapter, approved profile/authentication
strategy, target environment, object ownership, and deployment workflow before
running dbt.

## Model areas

- `models/silver/staging/`
- `models/silver/intermediate/`
- `models/gold/marts/`
- `tests/` - dbt tests, separate from the root Python test directory.
- `macros/` - reusable SQL macros when needed.
- `snapshots/` - approved history capture when needed.
