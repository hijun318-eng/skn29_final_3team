from dataclasses import replace
from datetime import date
from pathlib import Path
from sys import path

import pytest


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.contracts import AnalysisRequest, ErrorCode, RequestContext
from app.services.context_builder import (
    ContextAsset,
    ContextBuildError,
    ContextBuildErrorCode,
    ContextBuildRequest,
    ContextPackageBuilder,
)
from app.services.pipeline_support import PipelineSupport


ASSET = ContextAsset("urn:room", "serving.analytics.room", ("business_date",))


def _request(**changes):
    values = {
        "context_release": "f" * 64,
        "policy_version": "policy-v1",
        "time_version": "kr-calendar:v1:" + "a" * 64,
        "entitlement_hash": "entitlement-v1",
        "assets": (ASSET,),
        "token_count": 10,
        "model_context_tokens": 24_000,
        "context_release_id": "00000000-0000-0000-0000-000000000201",
        "context_release_key": "answervice-p0",
        "context_release_version": 1,
        "time_policy_id": "kr-calendar:v1:" + "a" * 64,
        "route_type": "GENERAL",
        "as_of": "2026-08-12",
        "timezone": "Asia/Seoul",
        "calendar_id": "gregorian-kr",
    }
    values.update(changes)
    return ContextBuildRequest(**values)


def _package(**changes):
    return ContextPackageBuilder().build(_request(**changes), frozenset({ASSET.urn}))


def test_route_template_and_time_policy_identifiers_are_hashed():
    general = _package()
    changed_time = _package(time_policy_id="kr-calendar:v2:" + "b" * 64)
    template = _package(route_type="TEMPLATE", template_id="room-template")

    assert general.time_policy_id.startswith("kr-calendar:v1:")
    assert general.route_type == "GENERAL"
    assert general.package_hash != changed_time.package_hash
    assert general.package_hash != template.package_hash


@pytest.mark.parametrize(
    ("package", "payload", "context", "route", "template", "code"),
    [
        (
            ContextPackageBuilder().build(
                replace(_request(), context_release_id=""), frozenset({ASSET.urn})
            ),
            AnalysisRequest(question="객실"),
            RequestContext(as_of=date(2026, 8, 12)),
            "GENERAL",
            None,
            ErrorCode.CONTEXT_INCOMPLETE,
        ),
        (
            _package(),
            AnalysisRequest(question="객실"),
            RequestContext(as_of=date(2026, 8, 12)),
            "TEMPLATE",
            "unbound-template",
            ErrorCode.ACCESS_DENIED,
        ),
        (
            _package(),
            AnalysisRequest(question="객실"),
            RequestContext(as_of=date(2026, 8, 11)),
            "GENERAL",
            None,
            ErrorCode.CONTEXT_INCOMPLETE,
        ),
        (
            _package(),
            AnalysisRequest(
                question="객실", parameters={"period_start": "2026-08-01"}
            ),
            RequestContext(as_of=date(2026, 8, 12)),
            "GENERAL",
            None,
            ErrorCode.CONTEXT_INCOMPLETE,
        ),
    ],
)
def test_single_g1_gate_fails_closed(
    package, payload, context, route, template, code
):
    violation = PipelineSupport.g1_error(
        package, payload, context, route, template
    )
    assert violation is not None
    assert violation[0] is code


def test_context_build_without_registry_resolver_fails_closed():
    support = PipelineSupport(object(), ContextPackageBuilder())

    with pytest.raises(ContextBuildError) as raised:
        support.build_context(
            AnalysisRequest(question="객실"),
            RequestContext(as_of=date(2026, 8, 12)),
            [],
        )

    assert raised.value.code is ContextBuildErrorCode.INACTIVE_RELEASE
