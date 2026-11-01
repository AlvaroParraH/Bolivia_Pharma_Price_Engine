from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from azure.core.exceptions import ResourceExistsError
import pyarrow as pa
import pyarrow.parquet as pq

from pipelines.ingestion.bronze import upload_snapshot as uploader


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.filename = "scrape_farmacorp_20261030T120000Z.parquet"
        self.path = self.directory / self.filename
        pq.write_table(pa.table({"run_id": ["run"], "retailer": ["farmacorp"]}), self.path)
        self.summary = {
            "run_id": "run", "status": "completed", "observations": 1,
            "output_files": {"parquet": self.filename},
        }
        self.save_summary()
        self.service = MagicMock()
        self.blob = self.service.get_blob_client.return_value.__enter__.return_value
        contents = self.path.read_bytes()
        properties = self.blob.get_blob_properties.return_value
        properties.size = len(contents)
        properties.content_settings.content_md5 = hashlib.md5(contents, usedforsecurity=False).digest()
        properties.metadata = {"sha256": hashlib.sha256(contents).hexdigest()}
        self.now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)

    def save_summary(self):
        (self.directory / "summary.json").write_text(json.dumps(self.summary))

    def upload(self, retailer="farmacorp"):
        return uploader.upload_snapshot(
            self.directory, retailer, self.service, "test-container", now=self.now,
            delete_after_upload=False,
        )

    def test_only_parquet_uploaded_using_upload_date(self):
        payloads = []
        self.blob.upload_blob.side_effect = lambda data, **kwargs: payloads.append(data.read())
        result = self.upload()
        self.assertEqual(result, f"bronze/farmacorp/20261101/{self.filename}")
        self.service.get_blob_client.assert_called_once_with(container="test-container", blob=result)
        self.blob.upload_blob.assert_called_once()
        kwargs = self.blob.upload_blob.call_args.kwargs
        self.assertFalse(kwargs["overwrite"])
        self.assertTrue(kwargs["validate_content"])
        self.assertEqual(kwargs["length"], self.path.stat().st_size)
        self.assertEqual(payloads, [self.path.read_bytes()])
        self.assertTrue(self.path.exists())
        self.assertTrue((self.directory / "summary.json").exists())

    def test_date_uses_utc_not_local_or_scrape_date(self):
        self.now = datetime(2026, 11, 1, 23, 30, tzinfo=timezone(timedelta(hours=-4)))
        self.assertIn("/20261102/", self.upload())

    def test_naive_date_rejected(self):
        self.now = datetime(2026, 11, 1)
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            self.upload()
        self.service.get_blob_client.assert_not_called()

    def test_all_retailers(self):
        for retailer in uploader.RETAILERS:
            with self.subTest(retailer=retailer):
                filename = f"scrape_{retailer}_20261030T120000Z.parquet"
                pq.write_table(pa.table({"run_id": ["run"], "retailer": [retailer]}), self.directory / filename)
                self.summary["output_files"]["parquet"] = filename
                self.save_summary()
                self.blob.get_blob_properties.return_value.size = (self.directory / filename).stat().st_size
                data = (self.directory / filename).read_bytes()
                self.blob.get_blob_properties.return_value.content_settings.content_md5 = hashlib.md5(data, usedforsecurity=False).digest()
                self.blob.get_blob_properties.return_value.metadata = {"sha256": hashlib.sha256(data).hexdigest()}
                self.assertEqual(self.upload(retailer), f"bronze/{retailer}/20261101/{filename}")

    def test_invalid_summary_rejected_before_network(self):
        for changes in (
            {"status": "running"}, {"status": "failed"}, {"observations": 2},
            {"observations": True}, {"run_id": "wrong"}, {"output_files": {}},
            {"output_files": {"parquet": "../other.parquet"}},
        ):
            original = self.summary.copy()
            with self.subTest(changes=changes):
                self.summary.update(changes)
                self.save_summary()
                with self.assertRaises(ValueError):
                    self.upload()
                self.service.get_blob_client.assert_not_called()
            self.summary = original

    def test_corrupt_parquet_rejected_before_network(self):
        self.path.write_bytes(b"not parquet")
        with self.assertRaises(pa.ArrowInvalid):
            self.upload()
        self.service.get_blob_client.assert_not_called()

    def test_warning_status_is_visible(self):
        self.summary["status"] = "completed_with_warnings"
        self.save_summary()
        with self.assertLogs(uploader.LOGGER, level="WARNING"):
            self.upload()

    def test_collision_and_upload_failure_keep_local_file(self):
        for error in (ResourceExistsError(), OSError("network interrupted")):
            with self.subTest(error=type(error).__name__):
                self.blob.upload_blob.side_effect = error
                with self.assertRaises(type(error)):
                    self.upload()
                self.assertTrue(self.path.exists())
                self.blob.get_blob_properties.assert_not_called()

    def test_verification_failure_is_not_success(self):
        self.blob.get_blob_properties.return_value.size = 1
        with self.assertRaisesRegex(RuntimeError, "verification failed"):
            self.upload()
        self.assertTrue(self.path.exists())

    def test_checksum_mismatch_is_not_success(self):
        self.blob.get_blob_properties.return_value.content_settings.content_md5 = b"wrong"
        with self.assertRaisesRegex(RuntimeError, "verification failed"):
            self.upload()

    def test_wrong_retailer_in_parquet_rejected(self):
        pq.write_table(pa.table({"run_id": ["run"], "retailer": ["hipermaxi"]}), self.path)
        with self.assertRaisesRegex(ValueError, "retailer"):
            self.upload()
        self.service.get_blob_client.assert_not_called()

    def test_cli_does_not_expose_azure_error_details(self):
        with patch("sys.argv", ["upload_snapshot", str(self.directory), "--retailer", "farmacorp"]), \
                patch.object(Path, "is_file", return_value=True), \
                patch.object(uploader, "dotenv_values", return_value={
                    "AZURE_STORAGE_CONNECTION_STRING": "private", "AZURE_STORAGE_CONTAINER": "test-container",
                }), patch.object(uploader.BlobServiceClient, "from_connection_string", return_value=self.service), \
                patch.object(uploader, "upload_snapshot", side_effect=ResourceExistsError("private")), \
                patch("sys.stderr") as stderr:
            with self.assertRaises(SystemExit) as error:
                uploader.main()
            self.assertEqual(error.exception.code, 1)
            self.assertNotIn("private", str(stderr.write.call_args_list))

    def prepare_cleanup(self):
        old = self.directory
        self.directory = old / "run"
        self.directory.mkdir()
        self.path.rename(self.directory / self.filename)
        self.path = self.directory / self.filename
        self.summary["output_files"] = {
            extension: str(Path(self.filename).with_suffix(f".{extension}"))
            for extension in ("csv", "jsonl", "parquet")
        }
        for extension in ("csv", "jsonl"):
            (self.directory / self.summary["output_files"][extension]).write_text("fixture")
        self.save_summary()

    def upload_with_cleanup(self):
        return uploader.upload_snapshot(
            self.directory, "farmacorp", self.service, "test-container",
            now=self.now, delete_after_upload=True,
        )

    def test_cleanup_removes_only_selected_run_after_verification(self):
        self.prepare_cleanup()
        unrelated = self.directory.parent / "other.txt"
        unrelated.write_text("keep")
        self.upload_with_cleanup()
        self.assertFalse(self.directory.exists())
        self.assertTrue(unrelated.exists())
        self.blob.get_blob_properties.assert_called_once()

    def test_cleanup_is_default_behavior(self):
        self.prepare_cleanup()
        uploader.upload_snapshot(
            self.directory, "farmacorp", self.service, "test-container", now=self.now,
        )
        self.assertFalse(self.directory.exists())

    def test_cleanup_upload_and_verification_failures_retain_all_files(self):
        self.prepare_cleanup()
        for error in (ResourceExistsError(), OSError("upload failed")):
            self.blob.upload_blob.side_effect = error
            with self.assertRaises(type(error)):
                self.upload_with_cleanup()
            self.assertEqual(len(list(self.directory.iterdir())), 4)
        self.blob.upload_blob.side_effect = None
        self.blob.get_blob_properties.return_value.size = 1
        with self.assertRaisesRegex(RuntimeError, "verification failed"):
            self.upload_with_cleanup()
        self.assertEqual(len(list(self.directory.iterdir())), 4)

    def test_cleanup_refuses_unexpected_files_before_upload(self):
        self.prepare_cleanup()
        (self.directory / "private.env").write_text("keep")
        with self.assertRaisesRegex(ValueError, "unexpected"):
            self.upload_with_cleanup()
        self.service.get_blob_client.assert_not_called()

    def test_cleanup_refuses_symlink_before_upload(self):
        self.prepare_cleanup()
        summary = self.directory / "summary.json"
        target = self.directory.parent / "external.json"
        summary.rename(target)
        summary.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "linked"):
            self.upload_with_cleanup()
        self.service.get_blob_client.assert_not_called()

    def test_cleanup_failure_reports_successful_upload_separately(self):
        self.prepare_cleanup()
        with patch.object(Path, "unlink", side_effect=PermissionError()):
            with self.assertRaisesRegex(uploader.CleanupError, "uploaded and verified"):
                self.upload_with_cleanup()
        self.assertTrue(self.path.exists())

    def test_cleanup_refuses_changes_during_upload(self):
        self.prepare_cleanup()
        def changed(data, **kwargs):
            (self.directory / "new.txt").write_text("keep")
        self.blob.upload_blob.side_effect = changed
        with self.assertRaises(uploader.CleanupError):
            self.upload_with_cleanup()
        self.assertTrue(self.path.exists())


if __name__ == "__main__":
    unittest.main()
