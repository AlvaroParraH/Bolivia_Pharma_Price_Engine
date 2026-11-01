# Role definitions

Place reviewed SQL for account and database role creation here. Confirm names,
scope, and responsibilities before execution; no roles are deployed yet.

Database roles are database-scoped privilege bundles and cannot be activated
as session roles. Keep role membership and hierarchy grants in
[grants/](../grants/README.md).

## Development account roles

[pharma_dev_roles.sql](pharma_dev_roles.sql) defines:

| Role | Intended responsibility |
|---|---|
| `PHARMA_DEV_DEPLOYER` | Deploy and administer approved development infrastructure |
| `PHARMA_DEV_INGESTOR` | Load staged observations into Bronze |
| `PHARMA_DEV_DBT` | Read Bronze and manage Silver/Gold dbt models |
| `PHARMA_DEV_READER` | Query approved Gold reporting objects |

These are account roles, not database roles. Names and comments describe intent;
they do not grant privileges or restrict access to development by themselves.
No object privileges, user assignments, role hierarchy grants, or ownership
transfers are included.

Before execution, confirm the target account and an authorized role with
`CREATE ROLE` (for example, `USERADMIN`). Role creation is separate from
grant administration. The active creating role becomes the role owner.

Statements use plain `CREATE ROLE`: an existing role fails explicitly rather
than being replaced or silently accepted. There is no migration runner.
Snowflake DDL statements commit independently, so an execution failure may
leave earlier roles created; inspect the result before retrying. Do not assume
the file is atomic or safe to rerun unchanged.
