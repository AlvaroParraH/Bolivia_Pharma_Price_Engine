# Silver table migrations

Place reviewed SQL changes for tables in the Silver schema here. No migration
runner or execution order is configured yet.

The category reference is maintained as the dbt
[product_categories seed](../../../../../pipelines/dbt/seeds/product_categories.csv).
Run `dbt seed --select product_categories` with the dbt profile targeting
`BOLIVIA_PHARMA_PRICE_ENGINE.SILVER` to create/populate the
`PRODUCT_CATEGORIES` table. dbt creates the table if it does not exist;
`dbt seed --full-refresh --select product_categories` rebuilds an existing seed
table and can replace its contents, so inspect the target and current data
before using full refresh. No seed has been executed and no table has been
deployed by this repository change. Apply its
explicit `SELECT` grant in
[pharma_dev_dbt.sql](../../../governance/grants/pharma_dev_dbt.sql) if another
authorized role creates and owns the table.

`ATC_SCOPE` preserves the supplied descriptive codes/ranges; it is not a verified
product ATC code or an automatic classification rule. Scopes overlap, and
classification requires ingredient, formulation, route, and reviewed mappings.
The supplied examples are unchanged, including oral rehydration salts under
IV fluids, which needs review before using it as a classification rule.
No additional unclassified category is inserted.

The seed's `category_id` is the intended unique identifier. Standard Snowflake
tables do not enforce primary-key uniqueness; validate IDs when modifying the
reference.
