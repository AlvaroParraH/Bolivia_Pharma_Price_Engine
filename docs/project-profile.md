# Project profile

This is a local planning seed. Review and update it as project facts are
confirmed. Do not put credentials, tokens, private keys, or sensitive
row-level data here.

## Project

- **Name:** bolivia_pharma_price_engine
- **Purpose:** Track monthly pharmacy product prices in Bolivia, identify
  increases and decreases, and compare the trends with the USD/BOB exchange
  rate.
- **Domain:** Bolivian pharmacy retail pricing and price trends.
- **Owner/team:** Not provided.
- **Primary consumers:** Twitter X
- **Initial environment:** dev
- **Data sensitivity:** public
- **Primary source type:** multiple source types

## Initial source scope

- [Farmacorp](https://farmacorp.com/)
- [Farmacias Chávez](https://www.farmaciaschavez.com.bo/)
- [Hipermaxi Farmacia Calacoto](https://www.hipermaxi.com/la-paz/farmacia-calacoto)

The planned analysis compares product prices month to month, identifies
increases and decreases, and examines their relationship to the US dollar to
Bolivian boliviano exchange rate. The exchange-rate source, product matching
rules across retailers, and observation schedule remain to be decided.

Before collecting data, review each site's terms and robots policy, use an
approved access method, and apply conservative request rates. Preserve
observation dates and source provenance; do not bypass access controls.

## Confirm before connecting or deploying

- Source access approval, product identity/matching rules, price/currency
  normalization, observation schedule, and ingestion/replay behavior.
- Exchange-rate data source and the timing/aggregation rule used to align it
  with each monthly price observation.
- Approved account/environment, roles, warehouse, database, schema, and object
  ownership for each environment; use the approved local authentication
  mechanism without recording connection values here.
- Data classification, retention, masking, sharing, and consumer access rules.
- dbt adapter/version, profile strategy, selected models, and deployment owner.
- Airflow runtime, provider versions, authentication, and release process.
- Testing, CI/CD approvals, rollback, and operational monitoring.

## Decisions and links

- Add Farmacias Chavez collection of paginated main-menu categories, including
  promotions, using a single Playwright browser/page. Store category-filterable
  timestamped CSV/JSONL/Parquet snapshots without selecting a delivery location.
  The robots endpoint returns HTML rather than usable rules; proceeding with
  a conservative public-page crawl was explicitly approved and is recorded as
  a warning. Location-specific catalog/stock coverage remains unverified.
- Use Playwright with Chromium for the initial Farmacorp browser automation.
  The initial collector processes every page in Ofertas and stores timestamped
  local JSONL/CSV/Parquet snapshots with regular and discounted prices. Future
  data filenames use `scrape_farmacorp_<UTC timestamp>.<format>`; existing
  snapshots remain unchanged. Other menu
  categories can be selected explicitly. The next collection scope is the nine
  remaining main menu categories, excluding Ofertas and nested subcategories.
  Each observation includes category name and URL for filtering. No schedule
  or warehouse load is configured.
- Traverse all linked category pages even when advertised totals change.
  Preserve repeated page observations and record count discrepancies as
  explicit warnings rather than presenting an exact, atomic catalog snapshot.
- Manage Python dependencies with uv using the root `pyproject.toml` and
  `uv.lock`; the project requires Python 3.11 or newer.

TODO: record remaining reviewed decisions and non-secret references.
