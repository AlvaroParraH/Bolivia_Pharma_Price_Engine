# Silver table migrations

Place reviewed SQL changes for tables in the Silver schema here. No migration
runner or execution order is configured yet.

[product_categories.sql](product_categories.sql) creates
`BOLIVIA_PHARMA_PRICE_ENGINE.SILVER.PRODUCT_CATEGORIES` and inserts the supplied
38-category reference. Confirm the database, Silver schema, ownership, and
authorized role before execution. No schema creation, grants, product assignments,
or live deployment are included.
After creating and populating the table, apply its explicit `SELECT` grant in
[pharma_dev_dbt.sql](../../../governance/grants/pharma_dev_dbt.sql) so dbt can
read this reference even when a deployment role owns it.

`ATC_SCOPE` preserves the supplied descriptive codes/ranges; it is not a verified
product ATC code or an automatic classification rule. Scopes overlap, and
classification requires ingredient, formulation, route, and reviewed mappings.
The supplied examples are unchanged, including oral rehydration salts under
IV fluids, which needs review before using it as a classification rule.
No additional unclassified category is inserted.

The primary key documents the intended unique category ID; standard Snowflake
tables do not enforce primary-key uniqueness. Validate IDs when modifying this
reference. Plain `CREATE TABLE` fails if the table exists; do not rerun the insert
against an already populated table. Statements commit separately: if insertion
fails after creation, inspect the table before retrying. This migration never
replaces an existing table.
