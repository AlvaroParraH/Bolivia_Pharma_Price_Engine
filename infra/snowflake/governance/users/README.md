# Development users

[pharma_airflow_dev.sql](pharma_airflow_dev.sql) defines the dedicated
`PHARMA_AIRFLOW_DEV` identity, currently configured as `PERSON` for a manual
Snowsight password/MFA login test with the development ingestor role.
It contains no password, key, or authentication configuration.
The ignored root `.env` stores this identity separately as
`AIRFLOW_SNOWFLAKE_USER=PHARMA_AIRFLOW_DEV` and `AIRFLOW_SNOWFLAKE_PASSWORD`,
with the following connection settings in the same section:

| Variable | Development value |
|---|---|
| `AIRFLOW_SNOWFLAKE_ACCOUNT` | `VLGIGMD-XC28657` |
| `AIRFLOW_SNOWFLAKE_DATABASE` | `BOLIVIA_PHARMA_PRICE_ENGINE` |
| `AIRFLOW_SNOWFLAKE_SCHEMA` | `BRONZE` |
| `AIRFLOW_SNOWFLAKE_WAREHOUSE` | `COMPUTE_WH` |
| `AIRFLOW_SNOWFLAKE_ROLE` | `PHARMA_DEV_INGESTOR` |
| `AIRFLOW_SNOWFLAKE_AUTHENTICATOR` | `snowflake` |

The original `SNOWFLAKE_*` settings remain unchanged. The password is the
temporary test password; a password change is required on first login.
Update the local password setting after changing it in Snowflake. These
Airflow-specific variables are mapped by Compose to the scheduler's
`SNOWFLAKE_*` environment. Updating them requires scheduler recreation and a
separate update of Airflow's saved `snowflake_pharma` connection.
MFA enrollment or challenges remain subject to Snowflake and account policies.
Do not disable or bypass those policies.

The password/MFA test does not prove unattended pipeline authentication works.
Airflow's saved connection may use these credentials, but password-change and
MFA requirements can prevent unattended login. For automation, use a `SERVICE` identity with
an approved supported method, such as key-pair authentication or OAuth;
Snowflake `SERVICE` users cannot authenticate with passwords.

[pharma_dbt_dev.sql](pharma_dbt_dev.sql) defines `PHARMA_DBT_DEV` as a
`PERSON` user for manual dbt development sessions. It also sets
`MUST_CHANGE_PASSWORD = TRUE`, with default role `PHARMA_DEV_DBT`,
warehouse `COMPUTE_WH`, and namespace `BOLIVIA_PHARMA_PRICE_ENGINE.SILVER`.
No password, key, or authentication secret is stored in this repository.

## Provisioning order

1. Confirm the development account, authorized administrative role, and target
   objects. Execute only approved statements; no SQL here runs automatically.
2. Create `PHARMA_DEV_INGESTOR` using its statement in
   [pharma_dev_roles.sql](../roles/pharma_dev_roles.sql) if it does not exist.
   Do not rerun unrelated role creation or replace existing roles.
3. Execute [pharma_airflow_dev.sql](pharma_airflow_dev.sql) using a role with
   `CREATE USER`, such as an authorized `USERADMIN` or `SECURITYADMIN` role.
4. Apply the existing [ingestor privileges](../grants/pharma_dev_ingestor.sql)
   after the warehouse, database, schema, stages, format, and tables exist.
   This existing grant set includes `INSERT` and `SELECT` for loading and
   validation, but no delete, update, object creation, or grant management.
5. Apply [user membership and role hierarchy](../grants/pharma_airflow_dev.sql)
   with an authorized grant administrator. The role is assigned to the user
   and inherited by `SYSADMIN`; no administrative role is assigned to the user.
6. Configure authentication securely outside tracked SQL. For the current
   manual test, log in to Snowsight, change the temporary password, and complete
   any required MFA enrollment. Verify noninteractive login separately before
   triggering Airflow loads.
   Setting `DEFAULT_ROLE` alone does not grant role membership.

Repeat steps 3 and 5 for [pharma_dbt_dev.sql](pharma_dbt_dev.sql) and
[../grants/pharma_dbt_dev.sql](../grants/pharma_dbt_dev.sql) when provisioning
dbt access. For dbt, use `PHARMA_DEV_DBT` and verify model permissions after
applying [pharma_dev_dbt.sql](../grants/pharma_dev_dbt.sql).

Verify the assignments using metadata statements:

```sql
SHOW GRANTS TO USER PHARMA_AIRFLOW_DEV;
SHOW GRANTS TO ROLE PHARMA_DEV_INGESTOR;
```

Plain `CREATE USER` fails if the user already exists; inspect existing identity
and grants rather than replacing them. Statements commit independently, so
check partial results before retrying. These files do not prove live deployment
or authentication readiness.
