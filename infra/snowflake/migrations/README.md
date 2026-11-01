# Snowflake migrations

Organize reviewed SQL changes first by schema, then by Snowflake object type.
The directories below represent the current BRONZE schema and planned SILVER
and GOLD schemas; confirm each schema exists before applying its migrations.
Each schema directory uses the same object-type layout.

Role definitions, access grants, and ownership transfers belong in
[governance/](../governance/README.md), separate from these object migrations.

```text
<schema>/
├── dynamic_tables/
├── functions/
├── pipelines/
├── policies/
├── procedures/
├── stages/
├── storage_integrations/
├── streamlits/
├── tables/
└── views/
```

These folders are organizational only. No migration runner or cross-folder
execution order has been selected. Keep migration filenames consistently
ordered when a runner is chosen, and do not assume it recursively discovers
these folders.

- `bronze/` — confirmed database schema.
- `silver/` — planned schema; not yet confirmed to exist.
- `gold/` — planned schema; not yet confirmed to exist.

Storage integrations are account-level objects, not schema-scoped objects.
The `storage_integrations/` folders organize their migrations by the layer
whose external stages use them. Define a shared integration in only one
location and reference it from other layers; do not duplicate its creation.
