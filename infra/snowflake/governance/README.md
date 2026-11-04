# Snowflake governance

Organize reviewed access-administration SQL separately from
[object migrations](../migrations/README.md).

- [roles/](roles/README.md): account and database role definitions.
- [grants/](grants/README.md): role hierarchy and approved access privileges.
- [ownership/](ownership/README.md): explicit object ownership assignments
  and transfers.

Local development role definitions are available in
[roles/](roles/README.md); no governance changes have been deployed and no
execution runner is configured. Folder order does not define execution order.
Before deployment, confirm the account/environment,
target roles and objects, required administrative privileges, dependencies,
and expected access changes; obtain explicit approval.

Keep schema-scoped masking and row access policy definitions in the existing
schema migration `policies/` folders. Storage integration definitions remain
in their migration folders; integration usage grants belong here.

Use least-privileged runtime roles and keep provisioning, ingestion, dbt,
and reader responsibilities separate. Do not put credentials in governance
scripts or use `ACCOUNTADMIN` as a pipeline runtime role.
