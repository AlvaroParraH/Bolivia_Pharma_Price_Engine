import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from pipelines.ingestion.bronze.load import upload_snapshot


class SnapshotUploadTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.snapshot = self.root / "20261102T183000Z_12345678"
        self.snapshot.mkdir()
        self.summary = {
            "retailer": "farmacorp",
            "run_id": self.snapshot.name,
            "status": "completed",
            "output_files": {
                "csv": "scrape_farmacorp_20261102T183000Z.csv",
                "jsonl": "scrape_farmacorp_20261102T183000Z.jsonl",
                "parquet": "scrape_farmacorp_20261102T183000Z.parquet",
            },
        }
        for filename in self.summary["output_files"].values():
            (self.snapshot / filename).write_bytes(b"snapshot data")
        (self.snapshot / "summary.json").write_text(json.dumps(self.summary), encoding="utf-8")

    @patch.object(upload_snapshot.BlobServiceClient, "from_connection_string")
    def test_uploads_only_parquet_under_retailer_and_utc_date(self, create_service):
        service = MagicMock()
        container = service.get_container_client.return_value
        create_service.return_value = service

        uploaded = upload_snapshot.upload_snapshot(
            self.snapshot, "farmacorp", "test-connection", "test-container",
        )

        expected = [
            f"farmacorp/20261102/{filename}"
            for filename in (
                self.summary["output_files"]["parquet"],
            )
        ]
        self.assertEqual(uploaded, expected)
        self.assertEqual(
            [call.args[0] for call in container.get_blob_client.call_args_list],
            expected,
        )
        upload_call = container.get_blob_client.return_value.upload_blob.call_args
        self.assertFalse(upload_call.kwargs["overwrite"])
        self.assertEqual(
            upload_call.kwargs["content_settings"].content_type, "application/vnd.apache.parquet",
        )
        service.close.assert_called_once()

    def test_local_csv_and_jsonl_are_not_required_for_upload(self):
        for data_format in ("csv", "jsonl"):
            (self.snapshot / self.summary["output_files"][data_format]).unlink()
        with patch.object(upload_snapshot.BlobServiceClient, "from_connection_string"):
            uploaded = upload_snapshot.upload_snapshot(
                self.snapshot, "farmacorp", "test-connection", "test-container",
            )
        self.assertEqual(uploaded, [
            "farmacorp/20261102/scrape_farmacorp_20261102T183000Z.parquet",
        ])

    def test_date_prefix_comes_from_utc_run_id(self):
        self.summary["run_id"] = "20261231T235959Z_abcdefgh"
        (self.snapshot / "summary.json").write_text(json.dumps(self.summary), encoding="utf-8")
        service = MagicMock()

        with patch.object(upload_snapshot.BlobServiceClient, "from_connection_string", return_value=service):
            uploaded = upload_snapshot.upload_snapshot(
                self.snapshot, "farmacorp", "test-connection", "test-container",
            )

        self.assertTrue(all(path.startswith("farmacorp/20261231/") for path in uploaded))

    @patch.object(upload_snapshot.BlobServiceClient, "from_connection_string")
    def test_completed_with_warnings_is_uploadable(self, create_service):
        self.summary["status"] = "completed_with_warnings"
        (self.snapshot / "summary.json").write_text(json.dumps(self.summary), encoding="utf-8")
        service = MagicMock()
        create_service.return_value = service

        upload_snapshot.upload_snapshot(
            self.snapshot, "farmacorp", "test-connection", "test-container",
        )

        self.assertEqual(service.get_container_client.return_value.get_blob_client.call_count, 1)

    def test_failed_or_mismatched_snapshot_is_rejected(self):
        self.summary["status"] = "failed"
        (self.snapshot / "summary.json").write_text(json.dumps(self.summary), encoding="utf-8")
        with patch.object(upload_snapshot.BlobServiceClient, "from_connection_string") as create_service:
            with self.assertRaisesRegex(ValueError, "status"):
                upload_snapshot.upload_snapshot(
                    self.snapshot, "farmacorp", "test-connection", "test-container",
                )
            create_service.assert_not_called()

        self.summary["status"] = "completed"
        (self.snapshot / "summary.json").write_text(json.dumps(self.summary), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "does not match"):
            upload_snapshot.upload_snapshot(
                self.snapshot, "hipermaxi", "test-connection", "test-container",
            )

    def test_missing_artifact_fails_before_connecting(self):
        (self.snapshot / self.summary["output_files"]["parquet"]).unlink()
        with patch.object(upload_snapshot.BlobServiceClient, "from_connection_string") as create_service:
            with self.assertRaisesRegex(FileNotFoundError, "missing"):
                upload_snapshot.upload_snapshot(
                    self.snapshot, "farmacorp", "test-connection", "test-container",
                )
            create_service.assert_not_called()

    def test_invalid_run_timestamp_is_rejected(self):
        self.summary["run_id"] = "not-a-timestamp"
        (self.snapshot / "summary.json").write_text(json.dumps(self.summary), encoding="utf-8")
        with patch.object(upload_snapshot.BlobServiceClient, "from_connection_string") as create_service:
            with self.assertRaisesRegex(ValueError, "UTC timestamp"):
                upload_snapshot.upload_snapshot(
                    self.snapshot, "farmacorp", "test-connection", "test-container",
                )
            create_service.assert_not_called()

    def test_snapshot_root_must_contain_exactly_one_snapshot(self):
        self.assertEqual(upload_snapshot.find_snapshot_directory(self.root), self.snapshot)
        another = self.root / "another"
        another.mkdir()
        (another / "summary.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            upload_snapshot.find_snapshot_directory(self.root)


if __name__ == "__main__":
    unittest.main()
