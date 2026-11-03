"""Bounded category timeout retries that retain already-written observations."""

from collections.abc import Callable
from datetime import datetime, timezone
import logging
import random
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


def collect_with_retries(
    collect: Callable[[int], dict[str, object]], *,
    category: dict[str, str], attempts: list[dict[str, object]],
    observations: Callable[[], int], save: Callable[[], None],
    delay: float, logger: logging.Logger,
) -> dict[str, object]:
    for attempt_number in range(1, 4):
        attempt: dict[str, object] = {
            **category, "attempt": attempt_number,
            "started_at": datetime.now(timezone.utc).isoformat(), "status": "running",
        }
        attempts.append(attempt)
        initial_count = observations()
        save()
        try:
            result = collect(attempt_number)
        except PlaywrightTimeoutError as error:
            attempt.update({
                "status": "timed_out", "error": str(error),
                "observations": observations() - initial_count,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })
            save()
            if attempt_number == 3:
                logger.error("%s: category timed out after 3 attempts", category["name"])
                raise
            logger.warning(
                "%s: attempt %d timed out; retaining raw rows and retrying category "
                "(attempt %d/3)", category["name"], attempt_number, attempt_number + 1,
            )
            time.sleep(max(10.0, delay) + random.uniform(0, 2))
        except BaseException as error:
            attempt.update({
                "status": "failed", "error": f"{type(error).__name__}: {error}",
                "observations": observations() - initial_count,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })
            save()
            raise
        else:
            attempt.update({
                "status": "completed", "observations": observations() - initial_count,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })
            save()
            return result
    raise AssertionError("Category retry loop ended without a result")
