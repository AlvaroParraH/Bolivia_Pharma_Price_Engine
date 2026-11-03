from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from pipelines.ingestion.bronze.extract import (
    scrape_farmacorp,
    scrape_farmacias_chavez,
    scrape_hipermaxi,
)


ROOT = Path(__file__).resolve().parents[1]


class EntrypointTests(unittest.TestCase):
    def test_module_help_without_network_access(self):
        for module in (
            "extract.scrape_farmacorp",
            "extract.scrape_farmacias_chavez",
            "extract.scrape_hipermaxi",
            "load.upload_snapshot",
        ):
            with self.subTest(module=module):
                result = subprocess.run(
                    [sys.executable, "-m", f"pipelines.ingestion.bronze.{module}", "--help"],
                    cwd=ROOT, capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage:", result.stdout)

    def test_default_snapshot_directories_remain_at_project_root(self):
        for module, retailer, output_index in (
            (scrape_farmacorp, "farmacorp", 2),
            (scrape_farmacias_chavez, "farmacias_chavez", 0),
            (scrape_hipermaxi, "hipermaxi", 0),
        ):
            with self.subTest(retailer=retailer), patch.object(
                sys, "argv", [f"scrape_{retailer}"],
            ), patch.object(module, "run") as run:
                module.main()
                run.assert_called_once()
                self.assertEqual(run.call_args.args[output_index], ROOT / "data" / retailer)


if __name__ == "__main__":
    unittest.main()
