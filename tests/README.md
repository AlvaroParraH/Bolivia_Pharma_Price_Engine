# Local tests

Keep Python unit tests here and keep dbt model tests under
`pipelines/dbt/tests/`. Use mocks or fixtures for external systems; tests should
not require Snowflake credentials or make account calls unless a separately
approved integration-test workflow explicitly provides them.

Run the Farmacorp tests from the project root:

```bash
uv run --no-env-file --locked python -m unittest discover -s tests -p 'test_farmacorp.py' -v
```

These use the standard library's unittest and the installed Playwright Chromium.
They cover localized money parsing, regular/discount prices, real local HTML
extraction, robots rules, category discovery, all-page traversal, count/duplicate
checks, HTTP/redirect errors, and explicit failure status for partial output.
Output tests verify timestamped filenames and equivalent CSV/JSONL/Parquet
records, including nullable prices, multiple page batches, empty output, and
Parquet finalization on handled collection failure.
Multi-buy `3 x 2` fixtures preserve the displayed unit price, keep calculated
discount fields null, and verify explicit category warnings. Invalid percentage
discounts still fail. A generated Farmacorp snapshot is passed to the mocked
Azure uploader to check the scraper-to-upload manifest contract.
Tests do not request the live Farmacorp site.
Empty-terminal-page fixtures cover a nonzero category heading with the explicit
no-results marker, retaining prior rows and count warnings. Unknown markers and
contradictory next-page links remain failures.

Run both retailer suites, including the shared snapshot writer regression
checks:

```bash
uv run --no-env-file --locked python -m unittest discover -s tests -p 'test_farma*.py' -v
```

Chavez coverage includes variable-decimal BOB prices, regular/discount prices,
full versus truncated names, offline Chromium DOM extraction, pagination,
duplicate-page detection, count warnings, explicit missing-robots approval,
failure manifests, and matching CSV/JSONL/Parquet records.

Run all three retailer suites:

```bash
uv run --no-env-file --locked python -m unittest discover -s tests -p 'test_*.py' -v
```

Entrypoint checks invoke `--help` for the relocated `extract/` scrapers and
Azure uploader under `extract/` without network access. Mocked CLI calls verify that
default snapshots still go to the project's root `data/<retailer>/` directory.

Snowflake load contract tests compare every scraper field and SQL cast with
its Bronze table definition, check provenance columns and safe COPY options,
and match mocked upload paths against retailer stages and filename patterns.
Temporary Parquet fixtures retain duplicate rows and nulls. These offline checks
do not connect to Snowflake or validate live privileges, object state, or SQL
acceptance. SQLFluff validation is blocked until that tool is available.

Airflow's separate runtime tests live under
`pipelines/orchestration/airflow/tests/`. SQL-operator tests use the locked
`airflow` dependency group, render each SQL file, verify retailer dependencies
and success-only trigger rules, dispatch to mocked Snowflake hooks, and ensure
query errors propagate. DAG parsing does not resolve credentials or connect.
See the [Airflow guide](../pipelines/orchestration/airflow/README.md) for container
commands; these tests never execute live COPY statements.

Hipermaxi tests cover dot-decimal prices, discounts, branch-restricted URLs,
DOM extraction, infinite-scroll completion signals, missing-sentinel failures,
bot-validation stops, robots rule precedence, failed manifests and equivalent
output formats. These are offline tests, not proof of live access or coverage.
All three scrapers have category retry fixtures covering up to three total timeout
attempts, retained raw rows, attempt summaries, recovery warnings, and no retry for
non-timeout errors. Farmacorp and Chavez fixtures exercise real pagination
restarting from page one, finalized Parquet row counts, and stopping before later
categories on exhaustion. Shared retry tests verify persisted state transitions,
attempt timestamps/errors, the 10-second delay floor, longer configured delays,
and jitter without sleeping or making network requests.
Interactive-mode tests cover visible-launch configuration, manual timeout and
window-close failures, allowed validation host, return URL/robots checks,
interrupted DOM operations and same-session return using local browser fixtures.
They do not interact with or solve the real Radware challenge.
Pacing tests verify the three-second floor plus 0-2 seconds random extra delay.
Local delayed-content fixtures verify category readiness before selection and
the 60-second readiness timeout configuration.
Regression fixtures cover loaded main categories with hidden “Todo” links,
explicit empty categories and subcategory-to-main navigation.
An animated-sentinel browser fixture reproduces the stability-wait timeout and
verifies that instant DOM scrolling loads the next batch exactly once and
requires the terminal marker. Scroll errors and no-progress timeouts remain
failures, without replaying previously written rows.

Azure snapshot upload tests use mocked Blob Storage clients. They verify that
only Parquet from completed snapshots is uploaded, artifact paths are namespaced
by retailer and UTC date (`YYYYMMDD`), and CSV/JSONL/summary stay local. They make no Azure
account calls.
