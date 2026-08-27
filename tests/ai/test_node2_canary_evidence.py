from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from scripts.verify_node2_canary_evidence import (
    EvidenceVerificationError,
    _definition_closure,
    _parse_sums,
    _safe_member,
    _verify_checksum_manifest,
    _verify_serving_resolution,
)


ROOT = Path(__file__).resolve().parents[2]


def test_safe_member_rejects_absolute_and_parent_paths() -> None:
    assert _safe_member("bundle/file.json")
    assert not _safe_member("../file.json")
    assert not _safe_member("bundle/../file.json")
    assert not _safe_member("/absolute/file.json")


def test_parse_sums_rejects_duplicate_members() -> None:
    digest = "0" * 64
    with pytest.raises(EvidenceVerificationError, match="duplicate"):
        _parse_sums(f"{digest}  file.json\n{digest}  file.json\n")


def test_checksum_manifest_requires_exact_membership_and_hashes() -> None:
    payload = b"verified evidence"
    digest = hashlib.sha256(payload).hexdigest()
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("bundle/file.txt", payload)
        archive.writestr("bundle/SHA256SUMS", f"{digest}  file.txt\n")
    archive_bytes.seek(0)
    with zipfile.ZipFile(archive_bytes) as archive:
        assert _verify_checksum_manifest(archive, root="bundle/") == 1


def test_definition_closure_includes_transitive_refs() -> None:
    contract = {
        "$defs": {
            "root": {"$ref": "#/$defs/child"},
            "child": {
                "type": "object",
                "properties": {"leaf": {"$ref": "#/$defs/leaf"}},
            },
            "leaf": {"type": "string"},
        }
    }

    assert _definition_closure(contract, ["root"]) == {"root", "child", "leaf"}


def test_historical_canary_manifest_precedes_the_2b_runtime_activation() -> None:
    canary = json.loads(
        (ROOT / "evals/node2_qwen35_2b_full3000_canary.v1.json").read_text(
            encoding="utf-8"
        )
    )
    runtime = json.loads(
        (ROOT / "src/modelops/model_runtime_manifest.v1.json").read_text(
            encoding="utf-8"
        )
    )
    aliases = {
        alias
        for profile in runtime["capacity_profiles"].values()
        for alias in profile["model_aliases"]
    }

    assert canary["status"] == "RUNPOD_CANARY_SMOKE_PASS_NOT_DEPLOYED"
    assert canary["active_runtime_changed"] is False
    assert canary["activation"]["production_switch_allowed"] is False
    assert canary["activation"]["existing_runtime_alias_to_preserve"] not in aliases
    assert canary["subject"]["served_model_alias"] in aliases


def test_canary_serving_lock_matches_the_manifest() -> None:
    canary = json.loads(
        (ROOT / "evals/node2_qwen35_2b_full3000_canary.v1.json").read_text(
            encoding="utf-8"
        )
    )

    assert _verify_serving_resolution(canary) == 183
