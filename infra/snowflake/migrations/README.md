# Snowflake migrations

Organize reviewed SQL changes first by schema, then by Snowflake object type.
The directories below represent the current BRONZE schema and planned SILVER
and GOLD schemas; confirm each schema exists before applying its migrations.
Each schema directory uses the same object-type layout.

```text
<schema>/
├── dynamic_tables/
├── functions/
├── pipelines/
├── policies/
├── procedures/
├── stages/
├── streamlits/
├── tables/
└── views/
```

These folders are organizational only. No migration runner or cross-folder
execution order has been selected. Keep migration filenames consistently
ordered when a runner is chosen, and do not assume it recursively discovers
these folders.

Bronze table, stage, and shared `file_formats/` definitions use the existing
`AZURE_BOLIVIA_PHARMA_BRONZE` account integration; they do not create or alter it.
See the [load guide](../../../pipelines/ingestion/bronze/load/README.md) for
deployment prerequisites, Azure paths, and load/replay boundaries.
Local SQL files do not establish the current deployment state.

- `bronze/` — confirmed database schema.
- `silver/` — planned schema; not yet confirmed to exist.
- `gold/` — planned schema; not yet confirmed to exist.
