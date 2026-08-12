from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from sys import path
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi.security import HTTPAuthorizationCredentials


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.adapters.i2_data_platform import I2DataPlatformAdapter  # noqa: E402
from app.context import ContextValidationError, analysis_context  # noqa: E402
from app.contracts import CONTRACT_VERSION, ErrorCode, RequestContext  # noqa: E402
from app.ports.data_platform import DataPlatformAccessDenied, DataPlatformNoAssets, DataPlatformUnavailable  # noqa: E402
from app.services.context_builder import (  # noqa: E402
    ContextAsset,
    ContextBuildRequest,
    ContextPackageBuilder,
)
from app.services.analysis_service import AnalysisService  # noqa: E402
from app.services.routing_service import RouteDecision  # noqa: E402
from app.contracts import AnalysisRequest, AnalysisStatus, RouteType  # noqa: E402


def _metadata(adapter, asset, domain="urn:li:domain:rooms"):
    return {
        "urn": asset["urn"],
        "name": f"DataHub {asset['name']}",
        "properties": {"description": "DataHub description"},
        "domain": {"domain": {"urn": domain, "properties": {"name": domain.rsplit(':', 1)[-1]}}},
        "ownership": {"owners": [{"owner": {"urn": "urn:li:corpuser:owner", "username": "owner"}}]},
        "glossaryTerms": {"terms": [{"term": {"urn": "urn:li:glossaryTerm:revenue", "properties": {"name": "Revenue"}}}]},
        "tags": {"tags": [{"tag": {"urn": "urn:li:tag:AI_SEARCH_ALLOWED", "properties": {"name": "AI_SEARCH_ALLOWED"}}}]},
        "lineage": {"relationships": [{"entity": {"domain": {"domain": {"urn": domain}}}}]},
        "schemaMetadata": {
            "name": asset["fqn"],
            "fields": [{"fieldPath": column, "description": f"{column} description"} for column in asset["columns"]],
        },
    }


def _live_dataset(asset):
    return {
        "urn": asset["urn"],
        "status": {"removed": False},
        "schemaMetadata": {
            "name": asset["fqn"],
            "fields": [{"fieldPath": column} for column in asset["columns"]],
        },
    }


def test_selected_profile_credential_drives_datahub_order_and_candidate_metadata():
    adapter = I2DataPlatformAdapter("http://trino:8080", "runtime-user")
    adapter._trino.health = lambda: True
    adapter._datahub_health = lambda: True
    expected = [next(asset for asset in adapter._assets if asset["fqn"] == "pms.public.pms_stays")]
    credentials = []
    adapter._datahub_search = lambda _query, credential: credentials.append(credential) or [
        _metadata(adapter, asset) for asset in expected
    ]
    adapter._datahub_dataset = lambda urn, credential: (
        credentials.append(credential)
        or _live_dataset(next(asset for asset in expected if asset["urn"] == urn))
    )
    context = RequestContext(
        user_id=UUID(int=1),
        as_of=date(2026, 8, 12),
        access_profile="pms_only",
    )

    with patch.dict("os.environ", {"DATAHUB_PMS_ONLY_TOKEN": "profile-credential"}, clear=False):
        assets = adapter.search_assets("호텔 객실 매출", context.model_dump(mode="json"))

    assert [item["urn"] for item in assets] == [item["urn"] for item in expected]
    assert set(credentials) == {"profile-credential"}
    assert assets[0]["description"] == "DataHub description"
    assert assets[0]["domain"] == "urn:li:domain:rooms"
    assert assets[0]["owners"] == ("owner",)
    assert assets[0]["glossary_terms"] == ("Revenue",)
    assert assets[0]["tags"] == ("AI_SEARCH_ALLOWED",)
    assert assets[0]["columns"][0]["description"].endswith("description")


def test_korean_business_question_expands_only_the_datahub_search_query():
    adapter = I2DataPlatformAdapter("http://trino:8080", "runtime-user")
    adapter._trino.health = lambda: True
    adapter._datahub_health = lambda: True
    asset = next(item for item in adapter._assets if item["fqn"] == "serving.analytics.hotel_daily_metrics")
    queries = []
    adapter._datahub_search = lambda query, _credential: queries.append(query) or (
        [_metadata(adapter, asset)] if "hotel_daily_metrics" in query else []
    )
    adapter._datahub_dataset = lambda _urn, _credential: _live_dataset(asset)
    context = RequestContext(user_id=UUID(int=1), access_profile="pms_only")

    with patch.dict("os.environ", {"DATAHUB_PMS_ONLY_TOKEN": "profile-credential"}, clear=False):
        assets = adapter.search_assets("저번주 매출 알려줘", context.model_dump(mode="json"))

    assert queries == ["저번주 매출 알려줘", "hotel_daily_metrics"]
    assert [item["urn"] for item in assets] == [asset["urn"]]


def test_domain_denial_and_missing_profile_credential_never_fall_back():
    adapter = I2DataPlatformAdapter("http://trino:8080", "runtime-user", datahub_token="generic-token")
    adapter._trino.health = lambda: True
    adapter._datahub_health = lambda: True
    asset = next(asset for asset in adapter._assets if asset["fqn"] == "pms.public.pms_stays")
    adapter._datahub_search = lambda _query, _credential: [_metadata(adapter, asset, "urn:li:domain:forbidden")]
    adapter._datahub_dataset = lambda _urn, _credential: _live_dataset(asset)
    context = RequestContext(user_id=UUID(int=1), access_profile="pms_only")

    with patch.dict("os.environ", {"DATAHUB_PMS_ONLY_TOKEN": "profile-credential"}, clear=False):
        with pytest.raises(DataPlatformAccessDenied):
            adapter.search_assets("호텔 객실 매출", context.model_dump(mode="json"))
    with patch.dict("os.environ", {"DATAHUB_PMS_ONLY_TOKEN": ""}, clear=False):
        with pytest.raises(DataPlatformUnavailable):
            adapter.search_assets("호텔 객실 매출", context.model_dump(mode="json"))


@pytest.mark.parametrize("violation", ["missing_tag", "serving_source_domain"])
def test_ai_search_tag_and_serving_lineage_domains_are_mandatory(violation):
    adapter = I2DataPlatformAdapter("http://trino:8080", "runtime-user")
    adapter._trino.health = lambda: True
    adapter._datahub_health = lambda: True
    asset = next(asset for asset in adapter._assets if asset["fqn"] == "serving.analytics.hotel_daily_metrics")
    metadata = _metadata(adapter, asset, "urn:li:domain:hotel-analytics")
    metadata["lineage"] = {
        "relationships": [{"entity": {"domain": {"domain": {"urn": "urn:li:domain:rooms"}}}}]
    }
    if violation == "missing_tag":
        metadata["tags"] = {"tags": []}
    else:
        metadata["lineage"] = {
            "relationships": [{"entity": {"domain": {"domain": {"urn": "urn:li:domain:facility"}}}}]
        }
    adapter._datahub_search = lambda _query, _credential: [metadata]
    adapter._datahub_dataset = lambda _urn, _credential: _live_dataset(asset)
    context = RequestContext(user_id=UUID(int=1), access_profile="integrated_revenue")
    with patch.dict("os.environ", {"DATAHUB_INTEGRATED_REVENUE_TOKEN": "profile-credential"}, clear=False):
        with pytest.raises(DataPlatformAccessDenied):
            adapter.search_assets("통합 매출", context.model_dump(mode="json"))


def test_empty_datahub_search_is_no_assets_not_denied_or_unavailable():
    adapter = I2DataPlatformAdapter("http://trino:8080", "runtime-user")
    adapter._trino.health = lambda: True
    adapter._datahub_health = lambda: True
    adapter._datahub_search = lambda _query, _credential: []
    context = RequestContext(user_id=UUID(int=1), access_profile="pms_only")
    with patch.dict("os.environ", {"DATAHUB_PMS_ONLY_TOKEN": "profile-credential"}, clear=False):
        with pytest.raises(DataPlatformNoAssets):
            adapter.search_assets("존재하지 않는 지표", context.model_dump(mode="json"))


@pytest.mark.parametrize(
    ("code", "expected"),
    [("FORBIDDEN", DataPlatformAccessDenied), ("INTERNAL_SERVER_ERROR", DataPlatformUnavailable)],
)
def test_datahub_graphql_errors_distinguish_access_denial_from_outage(code, expected):
    adapter = I2DataPlatformAdapter("http://trino:8080", "runtime-user")
    response = MagicMock()
    response.read.return_value = json.dumps(
        {"errors": [{"message": "redacted", "extensions": {"code": code}}]}
    ).encode()
    response.__enter__.return_value = response
    with patch("app.adapters.i2_data_platform.urlopen", return_value=response):
        with pytest.raises(expected):
            adapter._datahub_search("객실", "profile-credential")


def test_unknown_access_profile_is_access_denied_at_header_contract():
    request = type("Request", (), {"state": type("State", (), {"request_id": UUID(int=9)})()})()
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="runtime-test-token")
    with patch.dict("os.environ", {"AUTH_MODE": "test"}, clear=False):
        with pytest.raises(ContextValidationError) as denied:
            analysis_context(
                request, credentials, "2026-08-12", "trace-9", "Asia/Seoul",
                CONTRACT_VERSION, None, None, "unknown-profile",
            )
    assert denied.value.status_code == 403
    assert denied.value.code is ErrorCode.ACCESS_DENIED


def test_context_package_hash_and_assets_are_isolated_by_profile_domains_and_entitlement():
    asset = ContextAsset("urn:allowed", "serving.analytics.allowed", ("value",))
    denied = ContextAsset("urn:denied", "serving.analytics.denied", ("value",))
    builder = ContextPackageBuilder()

    def build(profile, domains, entitlement):
        return builder.build(
            ContextBuildRequest(
                "context-v1", "ACCESS-POLICY-v1.0.0", "2026-08-12", entitlement,
                (asset, denied), 10, 24_000,
                access_profile=profile, allowed_domains=domains,
                trino_principal=f"answervice_{profile}",
                datahub_principal=f"urn:li:corpuser:answervice_{profile}",
            ),
            frozenset({asset.urn}),
        )

    first = build("pms_only", ("urn:li:domain:rooms",), "entitlement-a")
    second = build("crm_only", ("urn:li:domain:membership",), "entitlement-b")
    assert [item.urn for item in first.assets] == ["urn:allowed"]
    assert first.package_hash != second.package_hash
    assert first.access_profile == "pms_only"
    assert first.allowed_domains == ("urn:li:domain:rooms",)


@pytest.mark.parametrize(
    ("failure", "code", "status"),
    [
        (DataPlatformAccessDenied("denied"), ErrorCode.ACCESS_DENIED, AnalysisStatus.BLOCKED),
        (DataPlatformUnavailable("down"), ErrorCode.QUERY_SOURCE_FAILED, AnalysisStatus.FAILED),
        (DataPlatformNoAssets("empty"), ErrorCode.INSUFFICIENT_EVIDENCE, AnalysisStatus.BLOCKED),
    ],
)
def test_analysis_error_contract_distinguishes_denied_unavailable_and_no_assets(failure, code, status):
    class Adapter:
        def search_assets(self, _query, _context):
            raise failure

    class Model:
        def generate(self, _node, _payload):
            raise AssertionError("search failure must stop before model")

    response = AnalysisService(Adapter(), Model()).analyze(
        AnalysisRequest(question="객실"),
        RequestContext(user_id=UUID(int=1), access_profile="pms_only"),
        RouteDecision(RouteType.GENERAL, None, True, True),
    )
    assert response.error.code is code
    assert response.data.status is status


def test_missing_profile_credential_has_safe_actionable_message():
    class Adapter:
        def search_assets(self, _query, _context):
            raise DataPlatformUnavailable("access profile credential is unavailable")

    response = AnalysisService(Adapter(), object()).analyze(
        AnalysisRequest(question="CRM 매출"),
        RequestContext(user_id=UUID(int=1), access_profile="integrated_operations"),
        RouteDecision(RouteType.GENERAL, None, True, True),
    )
    assert response.error.code is ErrorCode.QUERY_SOURCE_FAILED
    assert response.error.message == "선택한 데이터 접근 범위는 현재 사용할 수 없습니다. 관리자에게 문의해 주세요."
    assert "credential" not in response.error.message.lower()
