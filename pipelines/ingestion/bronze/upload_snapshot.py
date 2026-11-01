"""Upload finalized Parquet snapshots and clean up local files after verification."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re

from azure.core.exceptions import AzureError, ResourceExistsError
from azure.storage.blob import BlobServiceClient, ContentSettings
from dotenv import dotenv_values
import pyarrow.parquet as pq

LOGGER = logging.getLogger(__name__)
RETAILERS = ("farmacorp", "farmacias_chavez", "hipermaxi")


class CleanupError(RuntimeError):
    """The upload succeeded but local cleanup did not complete."""


def cleanup_candidates(
    directory: Path, output_files: dict[str, object], filename: str, run_id: str,
) -> list[Path]:
    resolved = directory.resolve()
    if (
        directory.is_symlink()
        or directory.name != run_id
        or Path.cwd().resolve().is_relative_to(resolved)
        or Path.home().resolve().is_relative_to(resolved)
    ):
        raise ValueError("Cleanup requires a dedicated run directory named after run_id")
    if set(output_files) != {"csv", "jsonl", "parquet"}:
        raise ValueError("Cleanup requires the three scraper output filenames")
    expected = {"summary.json"}
    for extension, name in output_files.items():
        if name != str(Path(filename).with_suffix(f".{extension}")):
            raise ValueError("Cleanup output filenames must match the Parquet basename")
        expected.add(name)
    candidates = list(directory.iterdir())
    if {path.name for path in candidates} != expected or any(
        path.is_symlink() or not path.is_file() for path in candidates
    ):
        raise ValueError("Cleanup refuses unexpected, missing, or linked run files")
    return sorted(candidates, key=lambda path: (path.name == "summary.json", path.name))


def upload_snapshot(
    directory: Path,
    retailer: str,
    service: BlobServiceClient,
    container: str,
    *,
    now: datetime | None = None,
    delete_after_upload: bool = True,
) -> str:
    """Upload only Parquet and remove the local run after verification by default."""
    if retailer not in RETAILERS:
        raise ValueError("Unsupported retailer")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9]|-(?!-)){1,61}[a-z0-9]", container):
        raise ValueError("Invalid Azure container name")
    uploaded_at = now if now is not None else datetime.now(timezone.utc)
    if uploaded_at.tzinfo is None or uploaded_at.utcoffset() is None:
        raise ValueError("Upload date must be timezone-aware")
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    if not isinstance(summary, dict):
        raise ValueError("Snapshot summary must be an object")
    status = summary.get("status")
    if status not in ("completed", "completed_with_warnings"):
        raise ValueError("Only completed snapshots can be uploaded")
    run_id = summary.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("Snapshot summary is missing run_id")
    output_files = summary.get("output_files")
    if not isinstance(output_files, dict):
        raise ValueError("Snapshot summary is missing output_files")
    filename = output_files.get("parquet")
    if not isinstance(filename, str) or not re.fullmatch(
        rf"scrape_{retailer}_\d{{8}}T\d{{6}}Z\.parquet", filename,
    ):
        raise ValueError("Snapshot Parquet filename does not match the retailer")
    datetime.strptime(filename.removeprefix(f"scrape_{retailer}_"), "%Y%m%dT%H%M%SZ.parquet")
    observations = summary.get("observations")
    if type(observations) is not int or observations <= 0:
        raise ValueError("Snapshot must contain a positive observation count")
    path = directory / filename
    if path.is_symlink():
        raise ValueError("Snapshot Parquet file must not be a symlink")
    candidates = (
        cleanup_candidates(directory, output_files, filename, run_id)
        if delete_after_upload else []
    )
    blob_name = f"bronze/{retailer}/{uploaded_at.astimezone(timezone.utc):%Y%m%d}/{filename}"
    with path.open("rb") as data:
        parquet = pq.ParquetFile(data)
        if parquet.metadata.num_rows != observations:
            raise ValueError("Parquet row count does not match the summary")
        for batch in parquet.iter_batches():
            values = batch.to_pydict()
            if not {"run_id", "retailer"}.issubset(values):
                raise ValueError("Parquet is missing run_id or retailer")
            if any(value != run_id for value in values["run_id"]):
                raise ValueError("Parquet run_id does not match the summary")
            if any(value != retailer for value in values["retailer"]):
                raise ValueError("Parquet retailer does not match the requested source")
        data.seek(0)
        sha256 = hashlib.sha256()
        md5 = hashlib.md5(usedforsecurity=False)
        size = 0
        while chunk := data.read(1024 * 1024):
            sha256.update(chunk)
            md5.update(chunk)
            size += len(chunk)
        data.seek(0)
        if status == "completed_with_warnings":
            LOGGER.warning("Uploading a snapshot marked completed_with_warnings")
        with service.get_blob_client(container=container, blob=blob_name) as blob:
            blob.upload_blob(
                data,
                length=size,
                overwrite=False,
                validate_content=True,
                content_settings=ContentSettings(
                    content_type="application/vnd.apache.parquet",
                    content_md5=md5.digest(),
                ),
                metadata={"sha256": sha256.hexdigest(), "scrape_status": status},
            )
            properties = blob.get_blob_properties()
            if (
                properties.size != size
                or properties.content_settings.content_md5 != md5.digest()
                or properties.metadata.get("sha256") != sha256.hexdigest()
            ):
                raise RuntimeError("Uploaded blob verification failed; local snapshot retained")
    LOGGER.info("Uploaded and verified %s", blob_name)
    if delete_after_upload:
        try:
            if cleanup_candidates(directory, output_files, filename, run_id) != candidates:
                raise ValueError("Run directory changed during upload")
            for candidate in candidates:
                candidate.unlink()
            directory.rmdir()
        except (OSError, ValueError) as error:
            raise CleanupError(
                "Blob uploaded and verified, but local cleanup failed; files may be partially removed"
            ) from error
        LOGGER.info("Removed local run directory after verified upload")
    return blob_name


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Finalized run directory with summary.json")
    parser.add_argument("--retailer", choices=RETAILERS, required=True)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)
    if not args.env_file.is_file():
        parser.error("Environment file does not exist")
    settings = dotenv_values(args.env_file, interpolate=False)
    connection = settings.get("AZURE_STORAGE_CONNECTION_STRING")
    container = settings.get("AZURE_STORAGE_CONTAINER")
    if not connection or not container:
        parser.error("Environment file must define AZURE_STORAGE_CONNECTION_STRING and AZURE_STORAGE_CONTAINER")
    try:
        with BlobServiceClient.from_connection_string(connection, logging_enable=False) as service:
            upload_snapshot(
                args.directory, args.retailer, service, container,
            )
    except CleanupError:
        parser.exit(1, "ERROR: Blob uploaded and verified, but local cleanup failed; files may be partially removed. Inspect the run before retrying.\n")
    except ResourceExistsError:
        parser.exit(1, "ERROR: Destination blob already exists; nothing overwritten. Local snapshot retained.\n")
    except AzureError as error:
        parser.exit(1, f"ERROR: Azure upload failed ({type(error).__name__}); check access/network settings. Local snapshot retained.\n")
    except (ValueError, OSError, RuntimeError) as error:
        LOGGER.error("Upload failed (%s); check snapshot and configuration", type(error).__name__)
        parser.exit(1, "ERROR: Upload did not complete; local snapshot retained.\n")


if __name__ == "__main__":
    main()
