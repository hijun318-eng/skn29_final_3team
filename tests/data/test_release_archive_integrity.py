"""과거 데이터 release archive의 파일 집합과 체크섬만 검증한다.

Archive SQL은 현재 Compose 초기화나 runtime schema discovery의 입력이 아니다. 이 테스트는
과거 산출물을 운영 정답으로 재사용하지 않고, 감사 이력이 변경되지 않았다는 사실만 보장한다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RELEASE_ROOT = (
    ROOT
    / "infrastructure"
    / "database"
    / "releases"
    / "walkerhill_v4_3_20260815_derived_1"
)
MANIFEST_PATH = RELEASE_ROOT / "manifest.json"


def _sha256(path: Path) -> str:
    """파일 bytes의 SHA-256을 계산한다."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_versioned_release_archive_matches_its_immutable_manifest() -> None:
    """Manifest에 기록된 모든 archive 파일의 크기와 digest를 exact 비교한다."""

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8-sig"))
    declared = {entry["relative_path"]: entry for entry in manifest["files"]}
    actual = {
        path.relative_to(RELEASE_ROOT).as_posix()
        for path in RELEASE_ROOT.rglob("*")
        if path.is_file() and path != MANIFEST_PATH
    }

    assert actual == set(declared)
    for relative, entry in declared.items():
        path = RELEASE_ROOT / relative
        assert path.stat().st_size == entry["bytes"], relative
        assert _sha256(path) == entry["sha256"], relative


def test_archive_is_not_a_runtime_success_claim() -> None:
    """Archive metadata가 과거 합성 release임을 명시하고 live readiness를 광고하지 않는다."""

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8-sig"))

    assert manifest["source_archive"]["sha256"]
    assert manifest["canonical_tree_sha256"]
    assert "runtime_status" not in manifest
    assert "production_ready" not in manifest
