from __future__ import annotations

import logging
import os
import time

from app.adapters.report_repository import PostgresReportWorkerRepository
from app.api.router import controller
from app.services.report_worker import ReportAnalysisRunner, ReportCommandWorker


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("answervice.report-worker")


def main() -> None:
    database_url = os.environ["APP_RUNTIME_DATABASE_URL"]
    repository = PostgresReportWorkerRepository(database_url)
    worker = ReportCommandWorker(
        repository,
        ReportAnalysisRunner(database_url, controller, repository),
    )
    poll_seconds = max(1.0, float(os.getenv("REPORT_WORKER_POLL_SECONDS", "5")))
    while True:
        try:
            run = worker.run_once()
            if run:
                logger.info("Report run completed: %s (%s)", run.run_id, run.status.value)
        except Exception:
            logger.exception("Report command failed")
        time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
