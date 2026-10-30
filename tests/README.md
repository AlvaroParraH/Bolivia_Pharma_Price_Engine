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
Tests do not request the live Farmacorp site.

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

Hipermaxi tests cover dot-decimal prices, discounts, branch-restricted URLs,
DOM extraction, infinite-scroll completion signals, missing-sentinel failures,
bot-validation stops, robots rule precedence, failed manifests and equivalent
output formats. These are offline tests, not proof of live access or coverage.
Interactive-mode tests cover visible-launch configuration, manual timeout and
window-close failures, allowed validation host, return URL/robots checks,
interrupted DOM operations and same-session return using local browser fixtures.
They do not interact with or solve the real Radware challenge.
Pacing tests verify the three-second floor plus 0-2 seconds random extra delay.
Local delayed-content fixtures verify category readiness before selection and
the 60-second readiness timeout configuration.
Regression fixtures cover loaded main categories with hidden “Todo” links,
explicit empty categories and subcategory-to-main navigation.
