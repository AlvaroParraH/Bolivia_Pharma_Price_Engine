"""Offline checks executed in the Airflow scheduler container."""

import runpy
import subprocess
import unittest
from pathlib import Path

class ScraperDagTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dag = runpy.run_path("/opt/airflow/dags/scrape_pharmacies.py")["dag"]

    def test_collection_contract(self) -> None:
        self.assertEqual(self.dag.dag_id, "scrape_pharmacy_prices")
        self.assertIsNone(self.dag.schedule)
        self.assertFalse(self.dag.catchup)
        self.assertEqual(self.dag.max_active_runs, 1)
        self.assertEqual(self.dag.max_active_tasks, 1)
        self.assertEqual(
            set(self.dag.task_ids),
            {"scrape_farmacorp", "scrape_farmacias_chavez", "scrape_hipermaxi"},
        )
        for task in self.dag.tasks:
            self.assertIn(
                f"-m pipelines.ingestion.bronze.extract.{task.task_id} ",
                task.bash_command,
            )
            self.assertIn(
                "-m pipelines.ingestion.bronze.extract.upload_snapshot ",
                task.bash_command,
            )
            self.assertEqual(task.retries, 0)
            self.assertFalse(task.upstream_task_ids)
            self.assertFalse(task.downstream_task_ids)
            self.assertFalse(task.do_xcom_push)
            self.assertIn("--output \"$snapshot_root\"", task.bash_command)
        self.assertIn("--main-categories", self.dag.get_task("scrape_farmacorp").bash_command)
        self.assertIn("--interactive", self.dag.get_task("scrape_hipermaxi").bash_command)
        self.assertNotIn("--exclude-category", self.dag.get_task("scrape_hipermaxi").bash_command)

    def test_chavez_requires_explicit_approval(self) -> None:
        for approved in (False, True):
            task = self.dag.get_task("scrape_farmacias_chavez")
            rendered = task.render_template(
                task.bash_command,
                {"params": {"allow_missing_chavez_robots": approved}},
            )
            self.assertEqual("--allow-missing-robots" in rendered, approved)
        self.assertFalse(self.dag.params["allow_missing_chavez_robots"])

    def test_scraper_entrypoints(self) -> None:
        for retailer in ("farmacorp", "farmacias_chavez", "hipermaxi"):
            result = subprocess.run(
                [
                    "/opt/pharma/.venv/bin/python", "-m",
                    f"pipelines.ingestion.bronze.extract.scrape_{retailer}", "--help",
                ],
                cwd="/opt/pharma", capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--output", result.stdout)
        result = subprocess.run(
            [
                "/opt/pharma/.venv/bin/python", "-m",
                "pipelines.ingestion.bronze.extract.upload_snapshot", "--help",
            ],
            cwd="/opt/pharma", capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--snapshot-root", result.stdout)

    def test_each_collection_uploads_after_scraping(self) -> None:
        for task in self.dag.tasks:
            scrape_index = task.bash_command.index("scrape_")
            upload_index = task.bash_command.index("upload_snapshot")
            self.assertLess(scrape_index, upload_index)
            self.assertIn("--snapshot-root", task.bash_command)

    def test_browser_and_snapshot_runtime(self) -> None:
        result = subprocess.run(
            ["/opt/pharma/.venv/bin/python", "-c", """
from playwright.sync_api import sync_playwright
with sync_playwright() as playwright:
    for headless in (True, False):
        browser = playwright.chromium.launch(
            headless=headless, env={"DISPLAY": "browser-desktop:99"}
        )
        try:
            page = browser.new_page()
            page.set_content("<title>Offline browser smoke test</title>")
            assert page.title() == "Offline browser smoke test"
        finally:
            browser.close()
"""],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        probe = Path("/opt/airflow/snapshots/.write-test")
        try:
            probe.write_text("test", encoding="ascii")
            self.assertEqual(probe.read_text(encoding="ascii"), "test")
        finally:
            probe.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
