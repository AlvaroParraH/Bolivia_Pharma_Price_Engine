# Bronze storage integration migrations

Place reviewed SQL changes for storage integrations used by Bronze external
stages here. Storage integrations are account-level objects, not schema objects;
this folder groups them by their intended use.

Keep a shared integration's definition in one location rather than duplicating
it across layers. No migration runner or execution order is configured yet.

## Azure Bronze integration

[azure_bolivia_pharma_bronze.sql](azure_bolivia_pharma_bronze.sql) defines the
account-level `AZURE_BOLIVIA_PHARMA_BRONZE` integration. It allows external
stages to reference the entire
`azure://blobprojects.blob.core.windows.net/bolivia-pharma-price-engine/`
container. The Bronze folder and integration name do not restrict access to
a Bronze blob prefix.

This definition was executed and verified with `DESC STORAGE INTEGRATION`
on 2026-11-01 in development account `VLGIGMD-XC28657` using an explicitly
approved one-time `ACCOUNTADMIN` operation. Azure consent, container RBAC,
stage creation, and file access validation were recorded as pending.
Current live state has not been reverified. Reuse the existing integration;
do not rerun creation for an object
that already exists.

Its non-secret Azure tenant GUID was
read from `AZURE_TENANT_ID` in the local `.env` and validated before insertion.
SQL does not automatically load environment variables; later `.env` changes
do not update this file. Review the tenant before deployment.
No Azure account key, connection string, SAS token, or client secret was copied
into the SQL.

### Deployment and Azure authorization

1. Confirm the target Snowflake account/environment and approved provisioning
   role with the account-level `CREATE INTEGRATION` privilege. Review the tenant,
   name, and container-wide access before executing the rendered statement.
   The script uses `CREATE`, not `CREATE OR REPLACE` or `IF NOT EXISTS`, so an
   existing integration fails explicitly without being replaced or ignored.
2. After approved creation, retrieve the consent information separately:

   ```sql
   DESC STORAGE INTEGRATION AZURE_BOLIVIA_PHARMA_BRONZE;
   ```

3. An authorized Azure administrator opens `AZURE_CONSENT_URL`, accepts consent,
   and assigns the Snowflake service principal identified by
   `AZURE_MULTI_TENANT_APP_NAME` the `Storage Blob Data Reader` role at the
   container scope. Allow time for the principal and role assignment to propagate.
4. Review Azure firewall/private-network requirements. Create a separately
   approved external stage with a URL inside the allowed location, using this
   integration. The stage creator needs parent database/schema access, schema
   `CREATE STAGE`, and integration `USAGE`.
5. Validate stage access and configure file formats/loading only with separate
   approval. No stage, grant, Azure role assignment, or data load is performed
   by this migration.

`ENABLED = TRUE` and allowed locations do not grant Azure read permissions or
enforce read-only access. Azure `Storage Blob Data Reader` provides that boundary;
do not grant Contributor unless write/delete operations are separately approved.
The scraper uploader uses its own Azure authentication, separate from this
Snowflake integration.

Reference: [Snowflake Azure storage setup](https://docs.snowflake.com/en/user-guide/data-load-azure-config).
