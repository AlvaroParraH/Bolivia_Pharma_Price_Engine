"""Upload only the Parquet artifact of a completed snapshot to Azure Blob Storage."""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from azure.storage.blob import BlobServiceClient, ContentSettings

RETAILERS = ("farmacorp", "farmacias_chavez", "hipermaxi")
DATA_FORMATS = ("parquet",)
CONTENT_TYPES = {
    "parquet": "application/vnd.apache.parquet",
}


def find_snapshot_directory(snapshot_root: Path) -> Path:
    if not snapshot_root.is_dir():
        raise FileNotFoundError(f"Snapshot root does not exist: {snapshot_root}")
    snapshots = [
        path for path in snapshot_root.iterdir()
        if path.is_dir() and (path / "summary.json").is_file()
    ]
    if len(snapshots) != 1:
        raise ValueError(
            f"Expected exactly one completed snapshot under {snapshot_root}, found {len(snapshots)}",
        )
    return snapshots[0]


def upload_snapshot(
    snapshot_directory: Path,
    retailer: str,
    connection_string: str | None = None,
    container_name: str | None = None,
) -> list[str]:
    if retailer not in RETAILERS:
        raise ValueError(f"Unsupported retailer: {retailer}")

    summary_path = snapshot_directory / "summary.json"
    with summary_path.open(encoding="utf-8") as summary_file:
        summary = json.load(summary_file)

    if summary.get("retailer") != retailer:
        raise ValueError(f"Snapshot retailer does not match {retailer}")
    if summary.get("status") not in {"completed", "completed_with_warnings"}:
        raise ValueError(f"Refusing to upload snapshot with status {summary.get('status')!r}")

    run_id = summary.get("run_id")
    if not isinstance(run_id, str) or not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
        raise ValueError("Snapshot summary has an invalid run_id")
    try:
        snapshot_date = datetime.strptime(run_id[:16], "%Y%m%dT%H%M%SZ").strftime("%Y%m%d")
    except ValueError as error:
        raise ValueError("Snapshot run_id must begin with a UTC timestamp in YYYYMMDDTHHMMSSZ format") from error

    output_files = summary.get("output_files")
    if not isinstance(output_files, dict):
        raise ValueError("Snapshot summary is missing output_files")

    files: list[tuple[Path, str]] = []
    for data_format in DATA_FORMATS:
        filename = output_files.get(data_format)
        if not isinstance(filename, str) or not filename or Path(filename).name != filename:
            raise ValueError(f"Snapshot summary has an invalid {data_format} filename")
        path = snapshot_directory / filename
        if not path.is_file():
            raise FileNotFoundError(f"Snapshot artifact is missing: {path}")
        files.append((path, data_format))

    connection_string = connection_string or os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    container_name = container_name or os.environ.get("AZURE_STORAGE_CONTAINER")
    if not connection_string:
        raise ValueError("AZURE_STORAGE_CONNECTION_STRING is required")
    if not container_name:
        raise ValueError("AZURE_STORAGE_CONTAINER is required")

    prefix = f"{retailer}/{snapshot_date}"
    uploaded: list[str] = []
    service = BlobServiceClient.from_connection_string(connection_string)
    try:
        container = service.get_container_client(container_name)
        for path, file_type in files:
            blob_name = f"{prefix}/{path.name}"
            with path.open("rb") as file_data:
                container.get_blob_client(blob_name).upload_blob(
                    file_data,
                    overwrite=False,
                    content_settings=ContentSettings(content_type=CONTENT_TYPES[file_type]),
                )
            uploaded.append(blob_name)
    finally:
        service.close()

    print(f"Uploaded {len(uploaded)} files under {container_name}/{prefix}/")
    return uploaded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--retailer", choices=RETAILERS, required=True)
    args = parser.parse_args()
    snapshot_directory = find_snapshot_directory(args.snapshot_root)
    upload_snapshot(snapshot_directory, args.retailer)


if __name__ == "__main__":
    main()
