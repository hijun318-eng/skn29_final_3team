"""Report Assistant 외부 전송 동의·receipt·transport 순서를 검증한다."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import sys
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app" / "backend"))

from app.adapters.model_schemas import openai_payload
from app.adapters.report_assistant import (
    ReportAssistantModelError,
    bind_report_assistant_model_execution,
    generate_report_change_proposal,
    prepare_report_assistant_model_invocation,
)
from app.services.report_assistant_external_transfer import (
    ExternalTransferConsentRequired,
    accept_report_assistant_external_transfer,
    authorize_report_assistant_transfer,
)
from src.modelops.runtime_config import (
    active_route_for_node,
    resolve_active_model_routes,
)
from tests.ai.test_report_assistant_contract import (
    REPORT_ASSISTANT_TURN_REQUEST,
    REPORT_ASSISTANT_TURN_RESPONSE,
)


class _TransferRepository:
    """원문 payload를 저장하지 않고 동의·receipt 호출 순서만 관측하는 저장소 대역이다."""

    def __init__(self, session, artifacts, events):
        self.session = session
        self.current_report_revision = session["base_revision"]
        self.artifacts = artifacts
        self.events = events
        self.disclosure = None
        self.consent = None
        self.receipts = []
        self.active_execution_id = None

    async def find_assistant_external_consent(self, request_id, binding_hash):
        self.events.append("consent_gate")
        if self.consent is None or self.consent["binding_hash"] != binding_hash:
            return None
        return dict(self.consent)

    async def create_assistant_transfer_disclosure(self, request_id, **values):
        if (
            self.disclosure is not None
            and self.consent is None
            and self.disclosure["binding_hash"] == values["binding_hash"]
            and self.disclosure["expires_at"] > datetime.now(timezone.utc)
        ):
            return dict(self.disclosure)
        self.disclosure = {
            **values,
            "assistant_request_id": request_id,
            "route_json": json.loads(json.dumps(values["route"])),
            "data_scopes_json": values["data_scopes"],
            "excluded_data_json": values["excluded_data"],
            "created_at": datetime.now(timezone.utc),
        }
        return dict(self.disclosure)

    async def get_assistant_transfer_disclosure(self, request_id, disclosure_id):
        if (
            self.disclosure is None
            or self.disclosure["assistant_request_id"] != request_id
            or self.disclosure["disclosure_id"] != disclosure_id
        ):
            raise KeyError(disclosure_id)
        return dict(self.disclosure)

    async def get_latest_assistant_transfer_disclosure(self, request_id):
        if (
            self.disclosure is None
            or self.disclosure["assistant_request_id"] != request_id
            or self.consent is not None
            or self.disclosure["expires_at"] <= datetime.now(timezone.utc)
        ):
            raise KeyError(request_id)
        return dict(self.disclosure)

    async def accept_assistant_external_transfer(
        self, request_id, disclosure_id, disclosure_hash
    ):
        disclosure = await self.get_assistant_transfer_disclosure(
            request_id, disclosure_id
        )
        if disclosure["disclosure_hash"] != disclosure_hash:
            raise ValueError("hash mismatch")
        self.consent = {
            "consent_id": str(uuid4()),
            "disclosure_id": disclosure_id,
            "assistant_request_id": request_id,
            "policy_version": disclosure["policy_version"],
            "disclosure_hash": disclosure_hash,
            "route_fingerprint": disclosure["route_fingerprint"],
            "binding_hash": disclosure["binding_hash"],
            "scope_hash": disclosure["scope_hash"],
            "consented_at": datetime.now(timezone.utc),
        }
        return dict(self.consent)

    async def get_assistant_session(self, request_id):
        if self.session["assistant_request_id"] != request_id:
            raise KeyError(request_id)
        return dict(self.session)

    async def get_draft_revision(self, definition_id, definition_version):
        if (
            str(self.session["session_definition_id"]) != str(definition_id)
            or self.session["session_definition_version"] != definition_version
        ):
            raise KeyError(definition_id)
        return self.current_report_revision

    async def get_version(self, definition_id, definition_version):
        await self.get_draft_revision(definition_id, definition_version)
        report = self.report
        return SimpleNamespace(
            definition_id=str(definition_id),
            version=definition_version,
            draft_revision=self.current_report_revision,
            title=report["title"],
            orientation=report["orientation"],
            currency_display_unit=report["currency_display_unit"],
            blocks=tuple(
                SimpleNamespace(
                    block_id=block["block_id"],
                    title=block["title"],
                    type=SimpleNamespace(value=block["type"]),
                    content=block["content"],
                    artifact_id=(
                        self.artifacts[0]["artifact_id"]
                        if block.get("artifact_ref") == "source_artifact"
                        else None
                    ),
                    x=block["x"],
                    y=block["y"],
                    w=block["w"],
                    h=block["h"],
                )
                for block in report["blocks"]
            ),
        )

    async def get_assistant_artifacts(self, request_id):
        await self.get_assistant_session(request_id)
        return [dict(item) for item in self.artifacts]

    async def get_assistant_artifact(self, artifact_id):
        return next(
            dict(item)
            for item in self.artifacts
            if str(item["artifact_id"]) == str(artifact_id)
        )

    async def insert_assistant_transfer_receipt(self, request_id, **values):
        if values.get("model_execution_id") != self.active_execution_id:
            raise KeyError("stale model execution")
        if any(
            item["assistant_request_id"] == request_id
            and item["model_execution_id"] == values["model_execution_id"]
            and item["attempt"] == values["attempt"]
            for item in self.receipts
        ):
            raise KeyError("duplicate model execution attempt")
        self.events.append("receipt")
        receipt = {"assistant_request_id": request_id, **values}
        self.receipts.append(receipt)
        return str(uuid4())


class ReportAssistantExternalTransferTests(unittest.IsolatedAsyncioTestCase):
    """동의 결속과 실제 provider request hash receipt를 네트워크 없이 검증한다."""

    def setUp(self):
        self.request_id = str(uuid4())
        self.artifact_id = str(uuid4())
        self.session = {
            "assistant_request_id": self.request_id,
            "session_definition_id": str(uuid4()),
            "session_definition_version": 3,
            "base_revision": 7,
            "result_artifact_id": None,
        }
        self.artifacts = (
            {
                "artifact_id": self.artifact_id,
                "artifact_checksum": "a" * 64,
            },
        )
        self.events = []
        self.repository = _TransferRepository(
            self.session, self.artifacts, self.events
        )
        self.repository.report = copy.deepcopy(REPORT_ASSISTANT_TURN_REQUEST["report"])
        self.execution_id = str(uuid4())
        self.repository.active_execution_id = self.execution_id
        environment = {
            "OPENAI_ENDPOINT": "https://api.openai.com/compatible",
            "OPENAI_API_KEY": "not-recorded-token",
            "OPENAI_MODEL": "gpt-5.4-mini",
        }
        self.route = active_route_for_node(
            resolve_active_model_routes(environment), "report_assistant_turn"
        )
        self._route_patch = patch(
            "app.services.report_assistant_external_transfer.resolve_active_model_routes",
            return_value=(self.route,),
        )
        self._route_patch.start()
        self.addCleanup(self._route_patch.stop)
        self._cost_environment = patch.dict(
            os.environ,
            {
                "REPORT_ASSISTANT_INPUT_USD_PER_MILLION": "1",
                "REPORT_ASSISTANT_OUTPUT_USD_PER_MILLION": "1",
                "REPORT_ASSISTANT_MAX_ESTIMATED_COST_USD": "100",
                "REPORT_ASSISTANT_MAX_MODEL_ATTEMPTS": "2",
            },
            clear=False,
        )
        self._cost_environment.start()
        self.addCleanup(self._cost_environment.stop)

    async def _consent_and_authorize(self, payload=None):
        model_payload = copy.deepcopy(payload or REPORT_ASSISTANT_TURN_REQUEST)
        with self.assertRaises(ExternalTransferConsentRequired) as raised:
            await authorize_report_assistant_transfer(
                self.repository,
                assistant_request_id=self.request_id,
                node="report_assistant_turn",
                payload=model_payload,
                session=self.session,
                artifacts=self.artifacts,
            )
        disclosure = raised.exception.disclosure
        await accept_report_assistant_external_transfer(
            self.repository,
            assistant_request_id=self.request_id,
            disclosure_id=str(disclosure.disclosure_id),
            disclosure_hash=disclosure.disclosure_hash,
            session=self.session,
            artifacts=self.artifacts,
        )
        authorization = await authorize_report_assistant_transfer(
            self.repository,
            assistant_request_id=self.request_id,
            node="report_assistant_turn",
            payload=model_payload,
            session=self.session,
            artifacts=self.artifacts,
        )
        return model_payload, authorization

    async def test_external_route_without_consent_stops_before_transport(self):
        transport = AsyncMock()
        with self.assertRaises(ExternalTransferConsentRequired):
            await authorize_report_assistant_transfer(
                self.repository,
                assistant_request_id=self.request_id,
                node="report_assistant_turn",
                payload=copy.deepcopy(REPORT_ASSISTANT_TURN_REQUEST),
                session=self.session,
                artifacts=self.artifacts,
            )
        transport.assert_not_awaited()
        self.assertEqual([], self.repository.receipts)
        serialized = json.dumps(self.repository.disclosure, default=str)
        self.assertNotIn("not-recorded-token", serialized)
        self.assertIn("https://api.openai.com", serialized)

    async def test_deployment_preapproval_skips_428_and_preserves_audit_binding(self):
        with patch.dict(
            os.environ,
            {"REPORT_ASSISTANT_EXTERNAL_TRANSFER_PREAUTHORIZED": "true"},
            clear=False,
        ):
            authorization = await authorize_report_assistant_transfer(
                self.repository,
                assistant_request_id=self.request_id,
                node="report_assistant_turn",
                payload=copy.deepcopy(REPORT_ASSISTANT_TURN_REQUEST),
                session=self.session,
                artifacts=self.artifacts,
            )

        self.assertIsNotNone(authorization.disclosure_id)
        self.assertIsNotNone(authorization.consent_id)
        self.assertEqual(
            "deployment_preapproval",
            self.repository.disclosure["route_json"]["authorization_mode"],
        )
        self.assertEqual(authorization.binding_hash, self.repository.consent["binding_hash"])

    async def test_repeated_missing_consent_reuses_one_pending_disclosure(self):
        payload = copy.deepcopy(REPORT_ASSISTANT_TURN_REQUEST)
        disclosures = []
        for _ in range(2):
            with self.assertRaises(ExternalTransferConsentRequired) as raised:
                await authorize_report_assistant_transfer(
                    self.repository,
                    assistant_request_id=self.request_id,
                    node="report_assistant_turn",
                    payload=payload,
                    session=self.session,
                    artifacts=self.artifacts,
                )
            disclosures.append(raised.exception.disclosure)
        self.assertEqual(disclosures[0].disclosure_id, disclosures[1].disclosure_id)
        self.assertEqual(disclosures[0].disclosure_hash, disclosures[1].disclosure_hash)

    async def test_consent_cost_execution_receipt_transport_order_and_payload_hash(self):
        payload, authorization = await self._consent_and_authorize()
        self.events.clear()
        original_preflight = __import__(
            "app.adapters.report_assistant", fromlist=["_enforce_model_cost_preflight"]
        )._enforce_model_cost_preflight

        def observed_preflight(*args, **kwargs):
            self.events.append("cost_preflight")
            return original_preflight(*args, **kwargs)

        with patch(
            "app.adapters.report_assistant._enforce_model_cost_preflight",
            side_effect=observed_preflight,
        ):
            invocation = prepare_report_assistant_model_invocation(
                "report_assistant_turn",
                payload,
                authorization=authorization,
                repository=self.repository,
            )
        invocation = bind_report_assistant_model_execution(
            invocation, self.execution_id
        )
        self.events.append("execution_gate")

        async def transport(*args, **kwargs):
            self.events.append("transport")
            return copy.deepcopy(REPORT_ASSISTANT_TURN_RESPONSE)

        with patch(
            "app.adapters.report_assistant.openai_transport",
            new=AsyncMock(side_effect=transport),
        ):
            await generate_report_change_proposal(payload, invocation=invocation)

        self.assertEqual(
            ["cost_preflight", "execution_gate", "receipt", "transport"],
            self.events,
        )
        expected_hash = hashlib.sha256(
            json.dumps(
                openai_payload(self.route.model, "report_assistant_turn", payload),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        receipt = self.repository.receipts[0]
        self.assertEqual(expected_hash, receipt["payload_hash"])
        self.assertEqual(
            "https://api.openai.com/compatible/v1/chat/completions",
            receipt["endpoint"],
        )
        self.assertNotIn("payload", receipt)

    async def test_external_route_never_retries_an_ambiguous_transport(self):
        payload, authorization = await self._consent_and_authorize()
        invocation = prepare_report_assistant_model_invocation(
            "report_assistant_turn",
            payload,
            authorization=authorization,
            repository=self.repository,
        )
        invocation = bind_report_assistant_model_execution(
            invocation, self.execution_id
        )
        self.events.clear()
        async def transport(*args, **kwargs):
            self.events.append("transport")
            return {"invalid": True}

        with patch(
            "app.adapters.report_assistant.openai_transport",
            new=AsyncMock(side_effect=transport),
        ), self.assertRaises(ReportAssistantModelError):
            await generate_report_change_proposal(payload, invocation=invocation)
        self.assertEqual(["receipt", "transport"], self.events)
        self.assertEqual([1], [item["attempt"] for item in self.repository.receipts])

    async def test_same_execution_attempt_is_one_shot_before_transport(self):
        """동일 fencing token·attempt의 invocation 재사용은 DB receipt에서 차단한다."""

        payload, authorization = await self._consent_and_authorize()
        invocation = bind_report_assistant_model_execution(
            prepare_report_assistant_model_invocation(
                "report_assistant_turn",
                payload,
                authorization=authorization,
                repository=self.repository,
            ),
            self.execution_id,
        )
        transport = AsyncMock(return_value=copy.deepcopy(REPORT_ASSISTANT_TURN_RESPONSE))
        with patch(
            "app.adapters.report_assistant.openai_transport", new=transport
        ):
            await generate_report_change_proposal(payload, invocation=invocation)
            with self.assertRaises(ReportAssistantModelError) as raised:
                await generate_report_change_proposal(payload, invocation=invocation)

        self.assertEqual("ASSISTANT_MODEL_EXECUTION_CONFLICT", raised.exception.code)
        transport.assert_awaited_once()
        self.assertEqual(1, len(self.repository.receipts))

    async def test_external_transport_has_an_absolute_wall_clock_timeout(self):
        payload, authorization = await self._consent_and_authorize()
        with patch.dict(
            os.environ,
            {"MODEL_TIMEOUT_SECONDS": "0.02"},
            clear=False,
        ):
            invocation = bind_report_assistant_model_execution(
                prepare_report_assistant_model_invocation(
                    "report_assistant_turn",
                    payload,
                    authorization=authorization,
                    repository=self.repository,
                ),
                self.execution_id,
            )

        async def never_finishes(*args, **kwargs):
            await asyncio.Event().wait()

        transport = AsyncMock(side_effect=never_finishes)
        with (
            patch("app.adapters.report_assistant.openai_transport", new=transport),
            self.assertRaises(ReportAssistantModelError) as raised,
        ):
            await generate_report_change_proposal(payload, invocation=invocation)
        self.assertEqual("REPORT_ASSISTANT_MODEL_TIMEOUT", raised.exception.code)
        transport.assert_awaited_once()
        self.assertEqual([1], [item["attempt"] for item in self.repository.receipts])

    async def test_payload_or_session_binding_change_requires_new_authorization(self):
        payload, authorization = await self._consent_and_authorize()
        invocation = prepare_report_assistant_model_invocation(
            "report_assistant_turn",
            payload,
            authorization=authorization,
            repository=self.repository,
        )
        invocation = bind_report_assistant_model_execution(
            invocation, self.execution_id
        )
        changed = copy.deepcopy(payload)
        changed["instruction"] = "different instruction"
        transport = AsyncMock()
        with patch(
            "app.adapters.report_assistant.openai_transport", new=transport
        ):
            with self.assertRaises(ReportAssistantModelError):
                await generate_report_change_proposal(
                    changed, invocation=invocation
                )
        transport.assert_not_awaited()
        self.assertEqual([], self.repository.receipts)

        self.repository.artifacts = self.artifacts
        self.repository.current_report_revision += 1
        with self.assertRaises(ValueError):
            await authorization.record_attempt(
                self.repository,
                attempt=1,
                payload_hash=invocation.payload_hash,
                model_execution_id=self.execution_id,
                minimum_lease_seconds=65,
            )
        self.assertEqual([], self.repository.receipts)

        self.repository.artifacts = (
            {**self.artifacts[0], "artifact_checksum": "b" * 64},
        )
        with self.assertRaises(ValueError):
            await authorization.record_attempt(
                self.repository,
                attempt=1,
                payload_hash=invocation.payload_hash,
                model_execution_id=self.execution_id,
                minimum_lease_seconds=65,
            )
        self.assertEqual([], self.repository.receipts)

    async def test_same_session_route_and_scope_requires_consent_for_a_different_node(self):
        payload, _authorization = await self._consent_and_authorize()
        review_route = active_route_for_node(
            (self.route,), "report_assistant_review"
        )
        self.assertEqual(self.route.route_fingerprint, review_route.route_fingerprint)
        with self.assertRaises(ExternalTransferConsentRequired):
            await authorize_report_assistant_transfer(
                self.repository,
                assistant_request_id=self.request_id,
                node="report_assistant_review",
                payload=payload,
                session=self.session,
                artifacts=self.artifacts,
            )

    async def test_invalid_artifact_checksum_is_rejected_before_disclosure(self):
        artifacts = ({**self.artifacts[0], "artifact_checksum": "A" * 64},)
        with self.assertRaises(ValueError):
            await authorize_report_assistant_transfer(
                self.repository,
                assistant_request_id=self.request_id,
                node="report_assistant_turn",
                payload=copy.deepcopy(REPORT_ASSISTANT_TURN_REQUEST),
                session=self.session,
                artifacts=artifacts,
            )

    async def test_internal_manifest_route_skips_consent_but_keeps_receipt(self):
        internal_route = replace(
            self.route,
            route_id="internal-report",
            data_boundary="internal",
            endpoint="https://node2.internal.example/compatible",
            approved_endpoint_origins=("https://node2.internal.example",),
        )
        with patch(
            "app.services.report_assistant_external_transfer.resolve_active_model_routes",
            return_value=(internal_route,),
        ):
            authorization = await authorize_report_assistant_transfer(
                self.repository,
                assistant_request_id=self.request_id,
                node="report_assistant_turn",
                payload=copy.deepcopy(REPORT_ASSISTANT_TURN_REQUEST),
                session=self.session,
                artifacts=self.artifacts,
            )
        self.assertIsNone(authorization.consent_id)
        self.assertIsNone(authorization.disclosure_id)
        self.assertIsNone(self.repository.disclosure)
        await authorization.record_attempt(
            self.repository,
            attempt=1,
            payload_hash="c" * 64,
            model_execution_id=self.execution_id,
            minimum_lease_seconds=65,
        )
        self.assertEqual("internal", self.repository.receipts[0]["data_boundary"])

    async def test_internal_label_cannot_bypass_destination_approval(self):
        internal_route = replace(
            self.route,
            route_id="internal-report",
            data_boundary="internal",
            approved_endpoint_origins=(),
        )
        with (
            patch(
                "app.services.report_assistant_external_transfer.resolve_active_model_routes",
                return_value=(internal_route,),
            ),
            self.assertRaises(ValueError),
        ):
            await authorize_report_assistant_transfer(
                self.repository,
                assistant_request_id=self.request_id,
                node="report_assistant_turn",
                payload=copy.deepcopy(REPORT_ASSISTANT_TURN_REQUEST),
                session=self.session,
                artifacts=self.artifacts,
            )

    async def test_disclosure_covers_artifact_metadata_destination_and_sensitive_content_warning(self):
        with self.assertRaises(ExternalTransferConsentRequired) as raised:
            await authorize_report_assistant_transfer(
                self.repository,
                assistant_request_id=self.request_id,
                node="report_assistant_turn",
                payload=copy.deepcopy(REPORT_ASSISTANT_TURN_REQUEST),
                session=self.session,
                artifacts=self.artifacts,
            )
        disclosure = raised.exception.disclosure
        self.assertIn("selected_artifact_metadata", disclosure.data_scopes)
        self.assertIn("민감정보", disclosure.content_warning)
        self.assertEqual(
            "https://api.openai.com",
            disclosure.provider_routes[0].destination_origin,
        )
        self.assertEqual("OpenAI API", disclosure.provider_routes[0].route_label)

    async def test_same_scope_new_instruction_reuses_session_consent(self):
        payload, authorization = await self._consent_and_authorize()
        changed = copy.deepcopy(payload)
        changed["instruction"] = "같은 공개 범위의 다음 보고서 변경"
        reused = await authorize_report_assistant_transfer(
            self.repository,
            assistant_request_id=self.request_id,
            node="report_assistant_turn",
            payload=changed,
            session=self.session,
            artifacts=self.artifacts,
        )
        self.assertEqual(authorization.consent_id, reused.consent_id)

    async def test_stale_execution_token_stops_at_receipt_before_transport(self):
        payload, authorization = await self._consent_and_authorize()
        invocation = bind_report_assistant_model_execution(
            prepare_report_assistant_model_invocation(
                "report_assistant_turn",
                payload,
                authorization=authorization,
                repository=self.repository,
            ),
            self.execution_id,
        )
        self.repository.active_execution_id = str(uuid4())
        transport = AsyncMock()
        with (
            patch("app.adapters.report_assistant.openai_transport", new=transport),
            self.assertRaises(ReportAssistantModelError) as raised,
        ):
            await generate_report_change_proposal(payload, invocation=invocation)
        self.assertEqual(
            "ASSISTANT_MODEL_EXECUTION_CONFLICT", raised.exception.code
        )
        transport.assert_not_awaited()
        self.assertEqual([], self.repository.receipts)

    def test_external_endpoint_origin_must_be_manifest_approved(self):
        with self.assertRaises(ValueError):
            resolve_active_model_routes(
                {
                    "OPENAI_ENDPOINT": "https://attacker.example/v1",
                    "OPENAI_API_KEY": "never-sent",
                    "OPENAI_MODEL": "gpt-5.4-mini",
                }
            )

    async def test_attempt_limit_above_database_contract_fails_before_transport(self):
        payload, authorization = await self._consent_and_authorize()
        transport = AsyncMock()
        with (
            patch.dict(
                os.environ,
                {"REPORT_ASSISTANT_MAX_MODEL_ATTEMPTS": "5"},
                clear=False,
            ),
            patch("app.adapters.report_assistant.openai_transport", new=transport),
            self.assertRaises(ReportAssistantModelError) as raised,
        ):
            prepare_report_assistant_model_invocation(
                "report_assistant_turn",
                payload,
                authorization=authorization,
                repository=self.repository,
            )
        self.assertEqual(
            "REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID", raised.exception.code
        )
        transport.assert_not_awaited()
        self.assertEqual([], self.repository.receipts)

    async def test_accepted_disclosure_is_not_recovered_and_new_scope_requires_new_disclosure(self):
        from app.services.report_assistant_external_transfer import (
            latest_report_assistant_transfer_disclosure,
        )

        payload = copy.deepcopy(REPORT_ASSISTANT_TURN_REQUEST)
        with self.assertRaises(ExternalTransferConsentRequired) as raised:
            await authorize_report_assistant_transfer(
                self.repository,
                assistant_request_id=self.request_id,
                node="report_assistant_turn",
                payload=payload,
                session=self.session,
                artifacts=self.artifacts,
            )
        disclosure = await latest_report_assistant_transfer_disclosure(
            self.repository, self.request_id
        )
        self.assertEqual(raised.exception.disclosure.disclosure_id, disclosure.disclosure_id)
        await accept_report_assistant_external_transfer(
            self.repository,
            assistant_request_id=self.request_id,
            disclosure_id=str(disclosure.disclosure_id),
            disclosure_hash=disclosure.disclosure_hash,
            session=self.session,
            artifacts=self.artifacts,
        )
        with self.assertRaises(KeyError):
            await latest_report_assistant_transfer_disclosure(
                self.repository, self.request_id
            )

        changed_scope_payload = {**payload, "history": [{"role": "user", "content": "추가"}]}
        with self.assertRaises(ExternalTransferConsentRequired) as changed:
            await authorize_report_assistant_transfer(
                self.repository,
                assistant_request_id=self.request_id,
                node="report_assistant_turn",
                payload=changed_scope_payload,
                session=self.session,
                artifacts=self.artifacts,
            )
        self.assertNotEqual(disclosure.disclosure_id, changed.exception.disclosure.disclosure_id)

    async def test_expired_disclosure_cannot_be_accepted_but_accepted_consent_has_no_clock_expiry(self):
        payload = copy.deepcopy(REPORT_ASSISTANT_TURN_REQUEST)
        with self.assertRaises(ExternalTransferConsentRequired) as raised:
            await authorize_report_assistant_transfer(
                self.repository,
                assistant_request_id=self.request_id,
                node="report_assistant_turn",
                payload=payload,
                session=self.session,
                artifacts=self.artifacts,
            )
        disclosure = raised.exception.disclosure
        self.repository.disclosure["expires_at"] = datetime.now(timezone.utc) - timedelta(
            seconds=1
        )
        with self.assertRaises(ValueError):
            await accept_report_assistant_external_transfer(
                self.repository,
                assistant_request_id=self.request_id,
                disclosure_id=str(disclosure.disclosure_id),
                disclosure_hash=disclosure.disclosure_hash,
                session=self.session,
                artifacts=self.artifacts,
            )
        self.assertIsNone(self.repository.consent)

        self.repository.disclosure["expires_at"] = datetime.now(timezone.utc) + timedelta(
            minutes=1
        )
        await accept_report_assistant_external_transfer(
            self.repository,
            assistant_request_id=self.request_id,
            disclosure_id=str(disclosure.disclosure_id),
            disclosure_hash=disclosure.disclosure_hash,
            session=self.session,
            artifacts=self.artifacts,
        )
        self.repository.disclosure["expires_at"] = datetime.now(timezone.utc) - timedelta(
            days=1
        )
        authorization = await authorize_report_assistant_transfer(
            self.repository,
            assistant_request_id=self.request_id,
            node="report_assistant_turn",
            payload=payload,
            session=self.session,
            artifacts=self.artifacts,
        )
        self.assertEqual(self.repository.consent["consent_id"], authorization.consent_id)
