"""Incremental, matching CSV, JSONL and Parquet snapshot output."""

from contextlib import ExitStack
import csv
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


class SnapshotWriter:
    def __init__(self, directory: Path, basename: str, fields: list[str]) -> None:
        self.files = {ext: f"{basename}.{ext}" for ext in ("csv", "jsonl", "parquet")}
        self.directory = directory
        self.schema = pa.schema([pa.field(name, pa.string()) for name in fields])
        self.fields = fields
        self.stack = ExitStack()

    def __enter__(self) -> "SnapshotWriter":
        try:
            self.json_file = self.stack.enter_context(
                (self.directory / self.files["jsonl"]).open("x", encoding="utf-8"),
            )
            csv_file = self.stack.enter_context(
                (self.directory / self.files["csv"]).open("x", encoding="utf-8", newline=""),
            )
            self.csv_file = csv_file
            self.csv_writer = csv.DictWriter(csv_file, fieldnames=self.fields)
            self.csv_writer.writeheader()
            self.parquet_writer = self.stack.enter_context(pq.ParquetWriter(
                self.directory / self.files["parquet"], self.schema, compression="snappy",
            ))
        except BaseException:
            self.stack.close()
            raise
        return self

    def write(self, rows: list[dict[str, str | None]]) -> None:
        if rows:
            self.parquet_writer.write_table(pa.Table.from_pylist(rows, schema=self.schema))
        for row in rows:
            self.json_file.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.csv_writer.writerow(row)
        self.json_file.flush()
        self.csv_file.flush()

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        return self.stack.__exit__(exc_type, exc_value, traceback)
