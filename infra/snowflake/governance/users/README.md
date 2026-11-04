# Development users

[pharma_airflow_dev.sql](pharma_airflow_dev.sql) defines the dedicated
`PHARMA_AIRFLOW_DEV` identity, currently configured as `PERSON` for a manual
Snowsight password/MFA login test with the development ingestor role.
It contains no password, key, or authentication configuration.
The temporary test password is stored only in the ignored root `.env` under
`SNOWFLAKE_AIRFLOW_TEST_PASSWORD`; a password change is required on first login.
MFA enrollment or challenges remain subject to Snowflake and account policies.
Do not disable or bypass those policies.

This manual test does not configure unattended pipeline authentication or
update Airflow's saved connection. For automation, use a `SERVICE` identity with
an approved supported method, such as key-pair authentication or OAuth;
Snowflake `SERVICE` users cannot authenticate with passwords.

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
   any required MFA enrollment. Do not copy this test login into Airflow.
   Setting `DEFAULT_ROLE` alone does not grant role membership.

Verify the assignments using metadata statements:

```sql
SHOW GRANTS TO USER PHARMA_AIRFLOW_DEV;
SHOW GRANTS TO ROLE PHARMA_DEV_INGESTOR;
```

Plain `CREATE USER` fails if the user already exists; inspect existing identity
and grants rather than replacing them. Statements commit independently, so
check partial results before retrying. These files do not prove live deployment
or authentication readiness.
