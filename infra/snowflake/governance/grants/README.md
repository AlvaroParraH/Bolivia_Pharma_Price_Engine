# Access grants

Place reviewed SQL for role hierarchy, approved user/service role assignments,
and database, schema, warehouse, object, and integration privileges here.
Include future grants only when their scope is explicitly approved.

Review inherited access and managed access schema rules. Avoid blanket
`ALL PRIVILEGES` or grant options as permission-error fixes. Keep ownership
transfers in [ownership/](../ownership/README.md).

## Development access

These local scripts target `BOLIVIA_PHARMA_PRICE_ENGINE` and `COMPUTE_WH`.
Nothing has been executed in Snowflake.

| Script | Access |
|---|---|
| [pharma_dev_deployer.sql](pharma_dev_deployer.sql) | Database/schema usage, schema creation, Bronze table/stage creation, Silver/Gold table/view creation, and Azure integration usage |
| [pharma_dev_ingestor.sql](pharma_dev_ingestor.sql) | Warehouse and Bronze parent usage; insert/select on the three scraping tables |
| [pharma_dev_dbt.sql](pharma_dev_dbt.sql) | Warehouse and parent usage; select on the three Bronze tables; Silver/Gold table/view creation |
| [pharma_dev_reader.sql](pharma_dev_reader.sql) | Warehouse, database, and Gold schema usage only; no data access yet |

### Prerequisites and pending grants

- All four account roles, the database, and the referenced objects must exist
  before their grants are executed. Silver and Gold are still planned schemas;
  create/confirm them separately before executing grants that reference them.
  Database `CREATE SCHEMA` lets the deployer provision those schemas, but does
  not create them. Bronze table migrations and the
  `AZURE_BOLIVIA_PHARMA_BRONZE` integration must also be deployed separately.
- The Bronze external stage name was not supplied, so stage `USAGE` for the
  ingestor remains pending. These grants alone do not enable file loading.
  An external-stage consumer needs stage `USAGE`, not integration `USAGE`;
  the deployer needs integration `USAGE` to create the stage.
- Gold reporting objects have not been selected. Add object-specific `SELECT`
  for the reader after those tables/views exist and are explicitly approved.
  No `ALL` or future grants are included.
- Ingestor `SELECT` supports load validation and replay checks; it has no
  `UPDATE`, `DELETE`, `TRUNCATE`, or object-creation privileges in these scripts.
- dbt owns models it creates. Creation privileges do not let it replace or
  read existing Silver/Gold objects owned by another role. Review any required
  model ownership transfer or dependency read grants separately. Configure dbt
  to target these exact schemas; schema creation is not granted to its role.
- The deployer has no account-level `CREATE INTEGRATION`, warehouse access,
  or blanket ownership grants. Integration provisioning requires a separately
  authorized administrator. Existing objects are not transferred to it here.

Before execution, confirm the account/environment and authorized grant
administrator. Use object owners or an approved role with `MANAGE GRANTS`,
respecting managed access schema rules. The scripts do not select a session
role, assign users, or establish role inheritance.

Grants are not an access revocation policy: existing and inherited privileges
remain unchanged and must be reviewed separately. Statements commit
independently; failures can leave a partially applied grant set. No execution
runner, automatic provisioning, or live validation is configured.
