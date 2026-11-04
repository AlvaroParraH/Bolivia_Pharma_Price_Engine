"""Offline operator checks; no metadata database or Snowflake connection."""

from datetime import timedelta
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

from airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator
from airflow.providers.snowflake.hooks.snowflake import SnowflakeHook


ROOT = Path("/opt/pharma") if Path("/opt/pharma").is_dir() else Path(__file__).resolve().parents[4]
DAG_FILE = (
    Path("/opt/airflow/dags/scrape_pharmacies.py")
    if ROOT == Path("/opt/pharma")
    else ROOT / "pipelines/orchestration/airflow/dags/scrape_pharmacies.py"
)
LOAD_DIRECTORY = ROOT / "pipelines/ingestion/bronze/load"


class SnowflakeLoadingTests(unittest.TestCase):
    def setUp(self):
        self.dag = runpy.run_path(str(DAG_FILE))["dag"]

    def test_parse_does_not_resolve_credentials_or_connect(self):
        with patch.object(SnowflakeHook, "get_conn") as connect, patch.object(
            SQLExecuteQueryOperator, "get_db_hook",
        ) as hook:
            runpy.run_path(str(DAG_FILE))
            connect.assert_not_called()
            hook.assert_not_called()

    def test_only_successful_retailer_upload_unlocks_its_load(self):
        for retailer in ("farmacorp", "farmacias_chavez", "hipermaxi"):
            with self.subTest(retailer=retailer):
                task = self.dag.get_task(f"load_{retailer}")
                self.assertIsInstance(task, SQLExecuteQueryOperator)
                self.assertEqual(task.conn_id, "snowflake_pharma")
                self.assertEqual(task.upstream_task_ids, {f"scrape_{retailer}"})
                self.assertEqual(
                    self.dag.get_task(f"scrape_{retailer}").downstream_task_ids,
                    {f"load_{retailer}"},
                )
                self.assertFalse(task.downstream_task_ids)
                self.assertEqual(task.trigger_rule, "all_success")
                self.assertEqual(task.retries, 0)
                self.assertEqual(task.execution_timeout, timedelta(hours=1))
                self.assertTrue(task.autocommit)
                self.assertFalse(task.split_statements)
                self.assertFalse(task.do_xcom_push)
                self.assertIsNone(task.handler)

    def test_sql_templates_resolve_to_exact_load_files(self):
        self.assertEqual(
            self.dag.template_searchpath, ["/opt/pharma/pipelines/ingestion/bronze/load"],
        )

        self.dag.template_searchpath = [str(LOAD_DIRECTORY)]
        for retailer in ("farmacorp", "farmacias_chavez", "hipermaxi"):
            with self.subTest(retailer=retailer):
                task = self.dag.get_task(f"load_{retailer}")
                self.assertEqual(task.sql, f"load_{retailer}.sql")
                rendered = task.render_template(task.sql, {})
                self.assertEqual(
                    rendered.strip(),
                    (LOAD_DIRECTORY / f"load_{retailer}.sql").read_text().strip(),
                )

    def test_operator_passes_rendered_copy_to_hook_and_propagates_errors(self):
        self.dag.template_searchpath = [str(LOAD_DIRECTORY)]
        for retailer in ("farmacorp", "farmacias_chavez", "hipermaxi"):
            for fail in (False, True):
                with self.subTest(retailer=retailer, fail=fail), patch.object(
                    SQLExecuteQueryOperator, "get_db_hook",
                ) as get_hook:
                    task = self.dag.get_task(f"load_{retailer}")
                    task.sql = task.render_template(task.sql, {})
                    hook = get_hook.return_value
                    if fail:
                        hook.run.side_effect = RuntimeError("COPY failed")
                        with self.assertRaisesRegex(RuntimeError, "COPY failed"):
                            task.execute({})
                    else:
                        task.execute({})
                    hook.run.assert_called_once()
                    self.assertEqual(hook.run.call_args.kwargs["sql"], task.sql)
                    self.assertTrue(hook.run.call_args.kwargs["autocommit"])
                    self.assertIsNone(hook.run.call_args.kwargs["handler"])


if __name__ == "__main__":
    unittest.main()
