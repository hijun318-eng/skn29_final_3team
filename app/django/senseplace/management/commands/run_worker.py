"""Django management command: run_worker.

PENDING 상태의 QueryRun job을 폴링하여 FastAPI /internal/v1/*를 호출하고
결과를 DB에 저장한다.

Job 상태머신:
    PENDING → RUNNING → SUCCEEDED | PARTIAL | NEEDS_DATA | FAILED

Usage:
    python manage.py run_worker
    python manage.py run_worker --poll-interval 5 --batch-size 10
    python manage.py run_worker --once

References:
    - docs/markdown/ai_docs/03_api_ai_integration_contract.md §4, §6
    - senseplace/models/platform.py (QueryRun)
    - senseplace/models/enums.py (JobStatusCode)
"""

from __future__ import annotations

import logging
import signal
import sys
import time
from typing import Any

import requests
from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from senseplace.models import QueryRun
from senseplace.models.enums import JobStatusCode

logger = logging.getLogger("senseplace.worker")

# FastAPI 내부 API 기본 URL
DEFAULT_FASTAPI_URL = "http://localhost:8001"

# 상태 전이 허용 맵
_VALID_TRANSITIONS: dict[str, set[str]] = {
    JobStatusCode.PENDING: {JobStatusCode.RUNNING, JobStatusCode.FAILED},
    JobStatusCode.RUNNING: {
        JobStatusCode.SUCCEEDED,
        JobStatusCode.PARTIAL,
        JobStatusCode.NEEDS_DATA,
        JobStatusCode.FAILED,
    },
    JobStatusCode.SUCCEEDED: set(),
    JobStatusCode.PARTIAL: set(),
    JobStatusCode.NEEDS_DATA: {JobStatusCode.RUNNING, JobStatusCode.FAILED},
    JobStatusCode.FAILED: set(),
}

# 시그널 플래그 — Graceful shutdown 지원
_shutdown_requested = False


def _handle_signal(signum: int, frame: Any) -> None:
    """SIGINT/SIGTERM 처리 — 다음 루프 종료."""
    global _shutdown_requested
    _shutdown_requested = True
    logger.info("종료 시그널 수신 (signal=%d). 현재 작업 완료 후 종료합니다.", signum)


class Command(BaseCommand):
    """PENDING job을 폴링하여 FastAPI에 위임하는 worker.

    AIC v2.0 §4의 worker 역할을 수행한다:
    1. PENDING 상태의 QueryRun을 조회
    2. 상태를 RUNNING으로 전이
    3. FastAPI /internal/v1/query-runs에 요청
    4. 응답에 따라 SUCCEEDED/PARTIAL/NEEDS_DATA/FAILED로 전이
    5. 결과를 QueryRun에 저장
    """

    help = "PENDING job을 폴링하여 FastAPI worker를 실행합니다."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--poll-interval",
            type=int,
            default=3,
            help="폴링 간격(초). 기본값: 3",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=10,
            help="한 번에 처리할 최대 job 수. 기본값: 10",
        )
        parser.add_argument(
            "--once",
            action="store_true",
            help="한 번만 실행하고 종료",
        )
        parser.add_argument(
            "--fastapi-url",
            type=str,
            default=DEFAULT_FASTAPI_URL,
            help=f"FastAPI 내부 API URL. 기본값: {DEFAULT_FASTAPI_URL}",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        poll_interval: int = options["poll-interval"]
        batch_size: int = options["batch-size"]
        once: bool = options["once"]
        fastapi_url: str = options["fastapi-url"].rstrip("/")

        # Graceful shutdown 시그널 등록
        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

        logger.info(
            "worker 시작: poll_interval=%ds batch_size=%d fastapi_url=%s",
            poll_interval,
            batch_size,
            fastapi_url,
        )
        self.stdout.write(
            f"worker 시작: poll={poll_interval}s batch={batch_size} "
            f"fastapi={fastapi_url}"
        )

        while True:
            if _shutdown_requested:
                logger.info("worker 종료 요청 수신. 루프를 종료합니다.")
                break

            processed = self._process_batch(batch_size, fastapi_url)

            if once:
                self.stdout.write(f"일회성 처리 완료: {processed}건 처리")
                break

            if processed == 0:
                time.sleep(poll_interval)

    def _process_batch(self, batch_size: int, fastapi_url: str) -> int:
        """한 배치의 PENDING job을 처리한다.

        Returns:
            처리된 job 수
        """
        pending_jobs = (
            QueryRun.objects.filter(status=JobStatusCode.PENDING)
            .order_by("created_at")[:batch_size]
        )

        processed = 0
        for job in pending_jobs:
            if _shutdown_requested:
                break

            success = self._process_job(job, fastapi_url)
            if success:
                processed += 1

        return processed

    def _process_job(self, job: QueryRun, fastapi_url: str) -> bool:
        """단일 job을 처리한다.

        Returns:
            성공 여부
        """
        # PENDING → RUNNING 전이
        if not self._transition_status(job, JobStatusCode.RUNNING):
            return False

        logger.info("job 처리 시작: job_id=%s question=%s", job.job_id, job.question_redacted[:60])

        try:
            result = self._call_fastapi_query_run(job, fastapi_url)
        except requests.ConnectionError:
            logger.error("FastAPI 연결 실패: job_id=%s", job.job_id)
            self._transition_status(job, JobStatusCode.FAILED)
            return True
        except requests.Timeout:
            logger.error("FastAPI 타임아웃: job_id=%s", job.job_id)
            self._transition_status(job, JobStatusCode.FAILED)
            return True
        except Exception:
            logger.exception("worker 처리 중 오류: job_id=%s", job.job_id)
            self._transition_status(job, JobStatusCode.FAILED)
            return True

        # FastAPI 응답에 따라 상태 전이
        target_status = result.get("job_status", JobStatusCode.SUCCEEDED)
        if target_status not in _VALID_TRANSITIONS.get(JobStatusCode.RUNNING, set()):
            target_status = JobStatusCode.SUCCEEDED

        self._save_result(job, result, target_status)
        logger.info(
            "job 처리 완료: job_id=%s status=%s",
            job.job_id,
            target_status,
        )
        return True

    def _call_fastapi_query_run(self, job: QueryRun, fastapi_url: str) -> dict[str, Any]:
        """FastAPI /internal/v1/query-runs를 호출한다.

        AIC v2.0 §5의 internal context를 포함하여 요청한다.

        Returns:
            FastAPI 응답 JSON
        """
        payload: dict[str, Any] = {
            "request_id": str(job.job_id),
            "run_id": str(job.query_run_id),
            "job_id": str(job.job_id),
            "actor_id": job.actor_id,
            "role_code": job.role_code,
            "scope_snapshot": job.scope_snapshot,
            "question": job.question_redacted,
            "dataset_version": job.dataset_version,
        }

        response = requests.post(
            f"{fastapi_url}/internal/v1/query-runs",
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def _save_result(
        self,
        job: QueryRun,
        result: dict[str, Any],
        target_status: str,
    ) -> None:
        """FastAPI 결과를 QueryRun에 저장한다."""
        job.query_plan = result.get("query_plan", {})
        job.sql_hash = result.get("sql_hash", "")
        job.row_count = result.get("row_count", 0)
        job.completed_at = timezone.now()

        self._transition_status(job, target_status)

    def _transition_status(self, job: QueryRun, target: str) -> bool:
        """job 상태를 안전하게 전이한다.

        Returns:
            전이 성공 여부
        """
        current = job.status
        allowed = _VALID_TRANSITIONS.get(current, set())
        if target not in allowed:
            logger.warning(
                "허용되지 않는 상태 전이: job_id=%s %s→%s",
                job.job_id,
                current,
                target,
            )
            return False

        QueryRun.objects.filter(query_run_id=job.query_run_id).update(
            status=target,
            completed_at=timezone.now() if target != JobStatusCode.RUNNING else None,
        )
        job.status = target
        return True
