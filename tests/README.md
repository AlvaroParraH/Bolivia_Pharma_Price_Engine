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
