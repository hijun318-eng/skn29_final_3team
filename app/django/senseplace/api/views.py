"""SensePlace 공개 API 뷰.

AIC v2.0 기준 7개 공개 엔드포인트:
- POST /api/v1/auth/login
- POST /api/v1/auth/logout
- GET  /api/v1/vocs
- GET  /api/v1/vocs/{id}
- POST /api/v1/jobs
- GET  /api/v1/jobs/{id}
- GET  /api/v1/reports

모든 응답은 {data, meta, error} envelope를 사용한다.
RBAC 데코레이터는 rbac/decorators.py의 기존 코드를 활용한다.

References:
    - docs/markdown/ai_docs/03_api_ai_integration_contract.md §3
    - senseplace/auth/views.py (로그인/로그아웃 로직 재사용)
    - senseplace/rbac/decorators.py (권한 검증)
    - src/common/contracts.py (ErrorCode, envelope 계약)
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from django.db.models import QuerySet
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from senseplace.api.envelope import (
    envelope_error,
    envelope_ok,
    error_authentication,
    error_forbidden,
    error_not_found,
    error_upstream,
    error_validation,
)
from senseplace.auth.views import login_view, logout_view
from senseplace.models import DataSource, DimDate, DimServiceArea, FactVoc, QueryRun, Report
from senseplace.models.enums import (
    DataSourceStatusCode,
    EngineTypeCode,
    HealthStatusCode,
    JobStatusCode,
    ReportStatusCode,
    ReportTypeCode,
    RoleCode,
    VocCategoryCode,
)
from senseplace.rbac.decorators import require_role, require_scope

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# VOC 응답 변환 헬퍼
# ---------------------------------------------------------------------------

_TOPIC_NAMES: dict[str, str] = dict(VocCategoryCode.CHOICES)
_SEVERITY_MAP: dict[str, str] = {
    "NEGATIVE": "danger",
    "NEUTRAL": "warn",
    "POSITIVE": "ok",
}

_REPORT_TYPE_LABELS: dict[str, str] = dict(ReportTypeCode.CHOICES)
_REPORT_STATUS_LABELS: dict[str, str] = {
    ReportStatusCode.DRAFT: "초안",
    ReportStatusCode.READY_FOR_REVIEW: "검토 중",
    ReportStatusCode.APPROVED: "확정",
    ReportStatusCode.REJECTED: "반려",
}


def _format_report_period(report_type: str, virtual_week_id: str) -> str:
    """보고서 유형에 따라 표시용 기간 라벨을 생성한다.

    - WEEKLY: DimDate에서 해당 주차의 시작일~종료일 (예: "07/20~07/26")
    - MONTHLY: "2026-06" → "2026년 06월"
    - QUARTERLY: "2026-Q2" → "2026 Q2"
    """
    if report_type == ReportTypeCode.WEEKLY:
        dates = DimDate.objects.filter(virtual_week_id=virtual_week_id).order_by("service_date")
        if dates.exists():
            start = dates.first().service_date
            end = dates.last().service_date
            return f"{start.month:02d}/{start.day:02d}~{end.month:02d}/{end.day:02d}"
        return virtual_week_id
    if report_type == ReportTypeCode.MONTHLY:
        parts = virtual_week_id.split("-")
        if len(parts) == 2:
            return f"{parts[0]}년 {parts[1]}월"
        return virtual_week_id
    if report_type == ReportTypeCode.QUARTERLY:
        return virtual_week_id
    return virtual_week_id


# ---------------------------------------------------------------------------
# DataSource 응답 변환 헬퍼 (ConnectionsPage 호환)
# ---------------------------------------------------------------------------

_ENGINE_LABELS: dict[str, str] = dict(EngineTypeCode.CHOICES)
_DOMAIN_MAP: dict[str, str] = {
    "PMS": "예약·투숙",
    "POS": "식음·구매",
    "CRM": "고객·멤버십",
    "FACILITY": "시설 운영",
    "BANQUET": "연회·매출",
}
_HEALTH_SCORE: dict[str, int | None] = {
    "HEALTHY": 99,
    "DEGRADED": 78,
    "DOWN": 0,
    "UNKNOWN": None,
}
_DS_STATUS_MAP: dict[str, str] = {
    "ACTIVE": "connected",
    "ERROR": "error",
    "DISABLED": "disabled",
    "DRAFT": "connected",
}
_SOURCE_RECORDS: dict[str, str] = {
    "PMS": "4.2M",
    "POS": "18.7M",
    "CRM": "620K",
    "FACILITY": "2.1M",
    "BANQUET": "340K",
}


def _format_relative_time(dt) -> str:
    """DateTimeField → 표시용 상대 시간 (예: '3분 전')."""
    if not dt:
        return "—"
    diff = timezone.now() - dt
    minutes = int(diff.total_seconds() / 60)
    if minutes < 1:
        return "방금 전"
    if minutes < 60:
        return f"{minutes}분 전"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}시간 전"
    days = hours // 24
    return f"{days}일 전"


def _datasource_to_dict(ds: DataSource) -> dict[str, Any]:
    """DataSource → ConnectionsPage 호환 응답 dict."""
    return {
        "data_source_id": str(ds.data_source_id),
        "source_code": ds.source_code,
        "name": ds.source_name,
        "vendor": _ENGINE_LABELS.get(ds.engine_type, ds.engine_type),
        "catalog": ds.trino_catalog,
        "domain": _DOMAIN_MAP.get(ds.source_code, ds.source_code),
        "status": _DS_STATUS_MAP.get(ds.status, "connected"),
        "health_status": ds.last_health_status,
        "health": _HEALTH_SCORE.get(ds.last_health_status),
        "records": _SOURCE_RECORDS.get(ds.source_code, "—"),
        "owner": ds.owner_team,
        "endpoint": f"{ds.trino_catalog}••••.internal",
        "sync": _format_relative_time(ds.last_health_at),
        "engine_type": ds.engine_type,
        "platform_instance": ds.platform_instance,
    }


def _build_area_map() -> dict[str, tuple[str, str]]:
    """service_area_id → (facility_name, zone) 매핑.

    display_name 예: "피자힐 (다이닝)" → ("피자힐", "다이닝")
    """
    area_map: dict[str, tuple[str, str]] = {}
    for area in DimServiceArea.objects.all():
        m = re.match(r"^(.+?)\s*\((.+?)\)$", area.display_name)
        if m:
            area_map[area.service_area_id] = (m.group(1), m.group(2))
        else:
            area_map[area.service_area_id] = (area.display_name, "")
    return area_map


def _voc_to_dict(v: FactVoc, area_map: dict[str, tuple[str, str]]) -> dict[str, Any]:
    """FactVoc → API 응답 dict (monitoring UI 호환 필드 포함)."""
    facility, zone = area_map.get(v.service_area_id, (v.service_area_id, ""))
    return {
        "voc_id": str(v.voc_id),
        "dataset_version": v.dataset_version,
        "received_at": v.received_at.isoformat() if v.received_at else None,
        "occurred_at": v.occurred_at.isoformat() if v.occurred_at else None,
        "service_area_id": v.service_area_id,
        "service_area_name": facility,
        "zone": zone,
        "topic_code": v.topic_code,
        "topic_name": _TOPIC_NAMES.get(v.topic_code, v.topic_code),
        "sentiment_label": v.sentiment_label,
        "severity": _SEVERITY_MAP.get(v.sentiment_label, "warn"),
        "review_text": v.review_text,
        "is_synthetic": v.is_synthetic,
    }

# ---------------------------------------------------------------------------
# JOB 상태머신 허용 전이
# ---------------------------------------------------------------------------
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


def _validate_transition(current: str, target: str) -> bool:
    """JOB 상태 전이 유효성을 검증한다."""
    allowed = _VALID_TRANSITIONS.get(current, set())
    return target in allowed


def _get_session_user(request: HttpRequest) -> dict[str, Any] | None:
    """세션에서 사용자 정보를 추출한다."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return {
        "user_id": user_id,
        "username": request.session.get("username"),
        "role_code": request.session.get("role_code"),
        "display_name": request.session.get("display_name"),
        "scope_snapshot": request.session.get("scope_snapshot", {}),
    }


# ===========================================================================
# 1. POST /api/v1/auth/login — session 로그인
# ===========================================================================
@csrf_exempt
@require_POST
def api_login(request: HttpRequest) -> JsonResponse:
    """세션 기반 로그인.

    기존 auth/views.py의 login_view를 재사용하여 응답 envelope를 일관시킨다.

    Request body (JSON):
        {"username": "staff.ops", "password": "demo1234"}

    Returns:
        200: 로그인 성공 (user 정보 + scope_snapshot)
        400: 필수 필드 누락
        401: 자격 증명 오류
        423: 로그인 시도 초과
    """
    return login_view(request)


# ===========================================================================
# 2. POST /api/v1/auth/logout — 로그아웃
# ===========================================================================
@csrf_exempt
@require_POST
def api_logout(request: HttpRequest) -> JsonResponse:
    """세션 로그아웃.

    기존 auth/views.py의 logout_view를 재사용한다.
    """
    return logout_view(request)


# ===========================================================================
# 3. GET /api/v1/vocs — VOC 목록 (페이지네이션, scope_snapshot 필터)
# ===========================================================================
@require_scope()
def voc_list(request: HttpRequest) -> JsonResponse:
    """VOC 목록 조회.

    세션의 scope_snapshot에 따라 topic_code별 필터링을 적용한다.
    페이지네이션: page, limit 쿼리 파라미터 (기본 page=1, limit=20).

    Returns:
        200: VOC 목록 + 페이지네이션 meta
        401: 미인증
        403: scope 미허용
    """
    scope = request.session.get("scope_snapshot", {})
    allowed_groups: list[str] = scope.get("metric_groups", [])

    # scope_snapshot metric_groups → topic_code 매핑
    _GROUP_TOPIC_MAP: dict[str, list[str]] = {
        "BREAKFAST": ["대기·혼잡", "청결·위생", "직원 서비스"],
        "FNB_VOC": ["대기·혼잡", "청결·위생", "직원 서비스", "가격·결제"],
        "GUEST_ROOM": ["시설 고장", "소음", "온도·환경", "청결·위생"],
        "GUEST_ROOM_SUMMARY": ["시설 고장", "소음", "온도·환경", "청결·위생"],
        "STAFF": ["직원 서비스"],
        "INCIDENTS": ["안전", "시설 고장", "소음"],
        "REPORTS": [],
    }

    allowed_topics: set[str] = set()
    for group in allowed_groups:
        allowed_topics.update(_GROUP_TOPIC_MAP.get(group, []))

    qs: QuerySet[FactVoc] = FactVoc.objects.all()
    if allowed_topics:
        qs = qs.filter(topic_code__in=allowed_topics)

    # 페이지네이션 파라미터 파싱
    try:
        page = max(1, int(request.GET.get("page", "1")))
    except (ValueError, TypeError):
        page = 1
    try:
        limit = max(1, min(100, int(request.GET.get("limit", "20"))))
    except (ValueError, TypeError):
        limit = 20

    total = qs.count()
    offset = (page - 1) * limit
    items = qs.order_by("-received_at")[offset : offset + limit]

    area_map = _build_area_map()
    vocs_data = [_voc_to_dict(v, area_map) for v in items]

    return envelope_ok(
        vocs_data,
        status=200,
        page=page,
        limit=limit,
        total=total,
    )


# ===========================================================================
# 4. GET /api/v1/vocs/{id} — VOC 상세
# ===========================================================================
@require_scope()
def voc_detail(request: HttpRequest, voc_id: str) -> JsonResponse:
    """VOC 상세 조회.

    scope_snapshot 필터를 적용하여 접근 권한을 검증한다.

    Returns:
        200: VOC 상세 정보
        401: 미인증
        403: scope 미허용
        404: VOC 미존재 또는 권한 밖
    """
    try:
        voc = FactVoc.objects.get(voc_id=voc_id)
    except FactVoc.DoesNotExist:
        return error_not_found("해당 VOC를 찾을 수 없습니다.")

    # scope 필터 적용
    scope = request.session.get("scope_snapshot", {})
    allowed_groups: list[str] = scope.get("metric_groups", [])

    _GROUP_TOPIC_MAP: dict[str, list[str]] = {
        "BREAKFAST": ["대기·혼잡", "청결·위생", "직원 서비스"],
        "FNB_VOC": ["대기·혼잡", "청결·위생", "직원 서비스", "가격·결제"],
        "GUEST_ROOM": ["시설 고장", "소음", "온도·환경", "청결·위생"],
        "GUEST_ROOM_SUMMARY": ["시설 고장", "소음", "온도·환경", "청결·위생"],
        "STAFF": ["직원 서비스"],
        "INCIDENTS": ["안전", "시설 고장", "소음"],
        "REPORTS": [],
    }

    allowed_topics: set[str] = set()
    for group in allowed_groups:
        allowed_topics.update(_GROUP_TOPIC_MAP.get(group, []))

    if allowed_topics and voc.topic_code not in allowed_topics:
        return error_not_found("해당 VOC를 찾을 수 없습니다.")

    area_map = _build_area_map()
    return envelope_ok(
        _voc_to_dict(voc, area_map),
        status=200,
    )


# ===========================================================================
# 5. POST /api/v1/jobs — job 생성 (worker 트리거)
# ===========================================================================
@csrf_exempt
@require_scope()
@require_role(
    RoleCode.OPERATIONS_MANAGER,
    RoleCode.FACILITY_MANAGER,
    RoleCode.EXTERNAL_REVIEWER,
)
def job_create(request: HttpRequest) -> JsonResponse:
    """Query job을 생성하고 202 Accepted를 반환한다.

    Request body (JSON):
        {"question": "...", "dataset_version": "gw-synthetic-1.0.0"}

    Returns:
        202: job_id + PENDING 상태
        400: 필수 필드 누락
        401: 미인증
        403: 권한 없음
    """
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return error_validation("JSON 형식의 요청 본문이 필요합니다.")

    question = (body.get("question") or "").strip()
    dataset_version = (body.get("dataset_version") or "").strip()

    if not question:
        return error_validation(
            "question 필드가 필요합니다.",
            details=[{"field": "question", "reason": "required"}],
        )
    if not dataset_version:
        return error_validation(
            "dataset_version 필드가 필요합니다.",
            details=[{"field": "dataset_version", "reason": "required"}],
        )

    user = _get_session_user(request)
    if not user:
        return error_authentication()

    job_id = uuid.uuid4()

    QueryRun.objects.create(
        query_run_id=job_id,
        job_id=job_id,
        actor_id=user["user_id"],
        role_code=user["role_code"],
        scope_snapshot=user["scope_snapshot"],
        question_redacted=question,
        dataset_version=dataset_version,
        status=JobStatusCode.PENDING,
    )

    logger.info(
        "job_created job_id=%s actor=%s question=%s",
        job_id,
        user["user_id"],
        question[:80],
    )

    return envelope_ok(
        {
            "job_id": str(job_id),
            "job_status": JobStatusCode.PENDING,
            "poll_url": f"/api/v1/jobs/{job_id}",
        },
        status=202,
    )


# ===========================================================================
# 6. GET /api/v1/jobs/{id} — job 상태 조회
# ===========================================================================
@require_scope()
def job_detail(request: HttpRequest, job_id: str) -> JsonResponse:
    """Job 상태 및 결과를 조회한다.

    job 소유자 또는 동일 scope을 가진 역할만 접근 가능하다.

    Returns:
        200: job 상태 + 결과 (있는 경우)
        401: 미인증
        403: 권한 없음
        404: job 미존재
    """
    try:
        query_run = QueryRun.objects.get(query_run_id=job_id)
    except QueryRun.DoesNotExist:
        return error_not_found("해당 작업을 찾을 수 없습니다.")

    user = _get_session_user(request)
    if not user:
        return error_authentication()

    # 소유자 또는 OPERATIONS_MANAGER만 접근 가능
    is_owner = query_run.actor_id == user["user_id"]
    is_ops = user["role_code"] == RoleCode.OPERATIONS_MANAGER
    if not is_owner and not is_ops:
        return error_forbidden("이 작업에 접근할 권한이 없습니다.")

    data: dict[str, Any] = {
        "job_id": str(query_run.query_run_id),
        "job_status": query_run.status,
        "actor_id": query_run.actor_id,
        "question": query_run.question_redacted,
        "dataset_version": query_run.dataset_version,
        "created_at": query_run.created_at.isoformat() if query_run.created_at else None,
        "completed_at": query_run.completed_at.isoformat() if query_run.completed_at else None,
    }

    # 완료된 경우 추가 정보
    if query_run.status in (
        JobStatusCode.SUCCEEDED,
        JobStatusCode.PARTIAL,
    ):
        data["query_plan"] = query_run.query_plan
        data["sql_hash"] = query_run.sql_hash
        data["row_count"] = query_run.row_count

    return envelope_ok(data, status=200)


# ===========================================================================
# 7. GET /api/v1/reports — 주간 보고서 목록
# ===========================================================================
@require_scope()
def report_list(request: HttpRequest) -> JsonResponse:
    """주간 보고서 목록을 조회한다.

    scope_snapshot의 metric_groups에 REPORTS가 포함된 역할만 조회 가능하다.
    페이지네이션: page, limit 쿼리 파라미터.

    Returns:
        200: 보고서 목록 + 페이지네이션 meta
        401: 미인증
        403: scope 미허용 (REPORTS 미포함)
    """
    scope = request.session.get("scope_snapshot", {})
    allowed_groups: list[str] = scope.get("metric_groups", [])

    if "REPORTS" not in allowed_groups:
        return error_forbidden("보고서 조회 권한이 없습니다.")

    qs: QuerySet[Report] = Report.objects.all()

    # 페이지네이션
    try:
        page = max(1, int(request.GET.get("page", "1")))
    except (ValueError, TypeError):
        page = 1
    try:
        limit = max(1, min(100, int(request.GET.get("limit", "20"))))
    except (ValueError, TypeError):
        limit = 20

    total = qs.count()
    offset = (page - 1) * limit
    items = qs.order_by("-created_at")[offset : offset + limit]

    reports_data = [
        {
            "report_id": str(r.report_id),
            "report_version": r.report_version,
            "virtual_week_id": r.virtual_week_id,
            "report_type": r.report_type,
            "report_type_label": _REPORT_TYPE_LABELS.get(r.report_type, r.report_type),
            "period": _format_report_period(r.report_type, r.virtual_week_id),
            "status": r.status,
            "status_label": _REPORT_STATUS_LABELS.get(r.status, r.status),
            "author": r.author_name,
            "is_synthetic": r.is_synthetic,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in items
    ]

    return envelope_ok(
        reports_data,
        status=200,
        page=page,
        limit=limit,
        total=total,
    )


# ===========================================================================
# 8. GET /api/v1/connections — 데이터 소스 연결 목록
# ===========================================================================
@require_scope()
def connection_list(request: HttpRequest) -> JsonResponse:
    """데이터 소스 연결 목록을 조회한다.

    ConnectionsPage(엔터프라이즈 프론트엔드)에서 사용하는
    사일로 DB 연결 상태를 반환한다.

    Returns:
        200: 데이터 소스 목록
        401: 미인증
        403: scope 미허용
    """
    items = DataSource.objects.all().order_by("source_code")
    data = [_datasource_to_dict(ds) for ds in items]

    return envelope_ok(
        data,
        status=200,
        total=len(data),
    )
