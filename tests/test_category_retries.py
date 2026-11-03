import logging
import unittest
from unittest.mock import Mock, patch

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from pipelines.ingestion.bronze.category_retries import collect_with_retries


class RetryTests(unittest.TestCase):
    def test_retry_delay_and_persisted_attempt_metadata(self):
        for delay, jitter, expected in [(3, 0, 10), (3, 2, 12), (15, 1, 16)]:
            with self.subTest(delay=delay, jitter=jitter), patch(
                "pipelines.ingestion.bronze.category_retries.time.sleep",
            ) as sleep, patch(
                "pipelines.ingestion.bronze.category_retries.random.uniform", return_value=jitter,
            ) as uniform:
                attempts = []
                saved_statuses = []
                result = {"warnings": []}
                collect = Mock(side_effect=[PlaywrightTimeoutError("stalled"), result])
                returned = collect_with_retries(
                    collect, category={"name": "Test", "url": "https://example.com/category"},
                    attempts=attempts, observations=lambda: 0,
                    save=lambda: saved_statuses.append([a["status"] for a in attempts]),
                    delay=delay, logger=logging.getLogger(__name__),
                )
                self.assertIs(returned, result)
                self.assertEqual([call.args[0] for call in collect.call_args_list], [1, 2])
                uniform.assert_called_once_with(0, 2)
                sleep.assert_called_once_with(expected)
                self.assertEqual(saved_statuses, [
                    ["running"], ["timed_out"], ["timed_out", "running"],
                    ["timed_out", "completed"],
                ])
                for number, attempt in enumerate(attempts, 1):
                    self.assertEqual(attempt["attempt"], number)
                    self.assertEqual(attempt["name"], "Test")
                    self.assertEqual(attempt["url"], "https://example.com/category")
                    self.assertEqual(attempt["observations"], 0)
                    self.assertLessEqual(attempt["started_at"], attempt["finished_at"])
                self.assertEqual(attempts[0]["error"], "stalled")
                self.assertNotIn("error", attempts[1])


if __name__ == "__main__":
    unittest.main()
