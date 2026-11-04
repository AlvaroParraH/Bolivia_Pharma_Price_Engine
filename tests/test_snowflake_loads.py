import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

import pyarrow.parquet as pq

from pipelines.ingestion.bronze.extract import (
    scrape_farmacorp,
    scrape_farmacias_chavez,
    scrape_hipermaxi,
    upload_snapshot,
)
from pipelines.ingestion.bronze.extract.snapshot import SnapshotWriter


ROOT = Path(__file__).resolve().parents[1]
LOADS = ROOT / "pipelines/ingestion/bronze/load"
MIGRATIONS = ROOT / "infra/snowflake/migrations/bronze"
FIELDS = {
    "farmacorp": list(scrape_farmacorp.Observation.__annotations__),
    "farmacias_chavez": scrape_farmacias_chavez.FIELDS,
    "hipermaxi": scrape_hipermaxi.FIELDS,
}


class SnowflakeLoadTests(unittest.TestCase):
    def test_explicit_mappings_match_scraper_fields_and_table_types(self):
        for retailer, fields in FIELDS.items():
            with self.subTest(retailer=retailer):
                sql = (LOADS / f"load_{retailer}.sql").read_text()
                table = (MIGRATIONS / "tables" / f"scraped_{retailer}_prices.sql").read_text()
                target = f"BOLIVIA_PHARMA_PRICE_ENGINE.BRONZE.SCRAPED_{retailer.upper()}_PRICES"
                self.assertIn(f"COPY INTO {target} (", sql)
                self.assertIn(f"CREATE TABLE {target} (", table)
                columns = re.search(r"COPY INTO [\w.]+ \((.*?)\)\s*FROM", sql, re.S)
                self.assertIsNotNone(columns)
                self.assertEqual(
                    [column.strip().lower() for column in columns[1].split(",")],
                    fields + ["source_file", "source_row_number"],
                )
                mappings = re.findall(r"\$1:(\w+)::([A-Z_]+(?:\(\d+, \d+\))?)", sql)
                self.assertEqual([field for field, _ in mappings], fields)
                for field, data_type in mappings:
                    expected_type = (
                        "TIMESTAMP_TZ" if field == "observed_at"
                        else "NUMBER(18, 2)" if field in {"price", "discount_price", "current_price"}
                        else "NUMBER(5, 2)" if field == "discount_percent"
                        else "NUMBER(38, 0)" if field == "batch"
                        else "VARCHAR"
                    )
                    self.assertEqual(data_type, expected_type)
                    self.assertIn(f"    {field.upper()} {data_type}", table)
                table_columns = re.findall(r"^    (\w+) (?:VARCHAR|TIMESTAMP_\w+|NUMBER)", table, re.M)
                self.assertEqual(
                    [column.lower() for column in table_columns],
                    fields + ["source_file", "source_row_number", "loaded_at"],
                )
                self.assertIn("METADATA$FILENAME", sql)
                self.assertIn("METADATA$FILE_ROW_NUMBER", sql)
                self.assertIn("LOADED_AT TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()", table)

    def test_actual_upload_paths_match_stages_and_copy_patterns(self):
        stages = (MIGRATIONS / "stages/scraped_prices_stages.sql").read_text()
        for retailer, fields in FIELDS.items():
            with self.subTest(retailer=retailer), TemporaryDirectory() as output:
                directory = Path(output)
                run_id = "20261103T221557Z_12345678"
                basename = f"scrape_{retailer}_20261103T221557Z"
                row = dict.fromkeys(fields, "example")
                row.update({
                    "run_id": run_id, "observed_at": "2026-11-03T22:15:57+00:00",
                    "retailer": retailer, "currency": "BOB", "price": "9.75",
                    "current_price": "9.75", "discount_price": None,
                    "discount_percent": None, "discount_label": None,
                    "regular_price_text": None, "availability_label": None,
                    "image_url": None,
                })
                if retailer == "hipermaxi":
                    row["batch"] = "1"
                with SnapshotWriter(directory, basename, fields) as writer:
                    writer.write([row, row])
                (directory / "summary.json").write_text(json.dumps({
                    "run_id": run_id, "retailer": retailer, "status": "completed_with_warnings",
                    "output_files": writer.files,
                }))
                with patch.object(upload_snapshot.BlobServiceClient, "from_connection_string"):
                    uploaded = upload_snapshot.upload_snapshot(
                        directory, retailer, "mock-connection", "bolivia-pharma-price-engine",
                    )
                sql = (LOADS / f"load_{retailer}.sql").read_text()
                stage_name = f"BOLIVIA_PHARMA_PRICE_ENGINE.BRONZE.{retailer.upper()}_SCRAPED_PRICES_STAGE"
                self.assertIn(f"FROM @{stage_name}", sql)
                definition = re.search(
                    rf"CREATE STAGE\s+{re.escape(stage_name)}\s+(.*?);", stages, re.S,
                )
                self.assertIsNotNone(definition)
                stage_url = re.search(r"URL = '([^']+)'", definition[1])[1]
                self.assertTrue(stage_url.startswith("azure://blobprojects.blob.core.windows.net/"))
                self.assertEqual(
                    urlsplit(stage_url).path,
                    f"/bolivia-pharma-price-engine/{retailer}/",
                )
                self.assertIn("STORAGE_INTEGRATION = AZURE_BOLIVIA_PHARMA_BRONZE", definition[1])
                self.assertIn("BOLIVIA_PHARMA_PRICE_ENGINE.BRONZE.PARQUET_SNAPSHOTS_FORMAT", definition[1])
                pattern = re.search(r"PATTERN = '([^']+)'", sql)[1]
                relative_file = uploaded[0].removeprefix(f"{retailer}/")
                self.assertIsNotNone(re.fullmatch(pattern, relative_file))
                self.assertIsNotNone(re.fullmatch(pattern, stage_url + relative_file))
                for invalid in (
                    relative_file.replace(".parquet", ".csv"),
                    relative_file.replace(".parquet", ".jsonl"),
                    relative_file + ".tmp",
                    relative_file.replace(f"scrape_{retailer}_", "scrape_other_"),
                    "20261103/summary.json",
                ):
                    self.assertIsNone(re.fullmatch(pattern, invalid))
                parquet = pq.read_table(directory / writer.files["parquet"])
                self.assertEqual(parquet.schema.names, fields)
                self.assertEqual(parquet.to_pylist(), [row, row])

    def test_loads_fail_on_errors_without_forcing_or_purging_files(self):
        for retailer in FIELDS:
            with self.subTest(retailer=retailer):
                sql = (LOADS / f"load_{retailer}.sql").read_text()
                for setting in (
                    "ON_ERROR = ABORT_STATEMENT", "FORCE = FALSE",
                    "PURGE = FALSE", "LOAD_UNCERTAIN_FILES = FALSE",
                ):
                    self.assertIn(setting, sql)
                self.assertEqual(sql.count(";"), 1)
                self.assertNotRegex(
                    sql.upper(),
                    r"\b(DELETE|TRUNCATE|DROP|DISTINCT|MERGE|TRY_CAST|TRY_TO_\w+)\b",
                )

    def test_infrastructure_does_not_replace_objects_or_recreate_integration(self):
        paths = [
            MIGRATIONS / "file_formats/parquet_snapshots_format.sql",
            MIGRATIONS / "stages/scraped_prices_stages.sql",
            *(MIGRATIONS / "tables" / f"scraped_{r}_prices.sql" for r in FIELDS),
        ]
        for path in paths:
            with self.subTest(path=path):
                sql = path.read_text().upper()
                self.assertNotIn("OR REPLACE", sql)
                self.assertNotIn("IF NOT EXISTS", sql)
                self.assertNotIn("CREATE STORAGE INTEGRATION", sql)
                self.assertNotIn("GRANT ", sql)
                self.assertNotIn("AZURE_TENANT_ID", sql)
        file_format = paths[0].read_text()
        self.assertIn("BOLIVIA_PHARMA_PRICE_ENGINE.BRONZE.PARQUET_SNAPSHOTS_FORMAT", file_format)
        self.assertIn("TYPE = PARQUET", file_format)


if __name__ == "__main__":
    unittest.main()
