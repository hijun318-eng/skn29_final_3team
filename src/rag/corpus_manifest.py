"""혼합 PDF·DOCX corpus manifest와 원본 checksum 경계를 검증한다."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping

from .source_bytes import read_bounded_source_bytes


CORPUS_MANIFEST_VERSION = "RagCorpusManifest.v1"
CORPUS_MANIFEST_VERSION_V2 = "RagCorpusManifest.v2"
_DOCUMENT_KINDS_V1 = frozenset({"MANUAL", "REFERENCE"})
_DOCUMENT_KINDS_V2 = frozenset({"MANUAL", "INTERNAL_REPORT", "REFERENCE"})
_SOURCE_SUFFIXES = frozenset({".pdf", ".docx"})
_MANUAL_ID = re.compile(r"^[A-Z][A-Z0-9-]{2,99}$")
_ROLE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_METADATA_KEYS = frozenset({"period", "department"})


@dataclass(frozen=True)
class CorpusManifestDocument:
    """원본 경로·식별자·접근 범위·업무 metadata를 봉인한 문서 선언이다."""

    source_file: str
    document_kind: str
    manual_id: str
    source_sha256: str
    source_version: str | None = None
    role_scope: tuple[str, ...] | None = None
    owner_team: str | None = None
    period: str | None = None
    department: str | None = None

    @property
    def included(self) -> bool:
        """참조 전용이 아닌 실제 검색·적재 대상인지 반환한다."""

        return self.document_kind != "REFERENCE"

    @property
    def source_format(self) -> str:
        """정규화된 source 경로에서 지원 파일 형식을 소문자로 반환한다."""

        return PurePosixPath(self.source_file).suffix.lower().lstrip(".")


@dataclass(frozen=True)
class CorpusManifest:
    """선언 문서와 실제 corpus directory의 byte 단위 일치를 보장한다."""

    documents: tuple[CorpusManifestDocument, ...]
    manifest_sha256: str
    schema_version: str = CORPUS_MANIFEST_VERSION

    @classmethod
    def load(cls, path: Path, manuals_dir: Path) -> "CorpusManifest":
        """manifest를 읽고 모든 지원 원본의 경로·식별자·SHA를 exact-match한다."""

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("RAG corpus manifest is unreadable") from error
        if (
            not isinstance(raw, dict)
            or set(raw) != {"schema_version", "documents"}
            or raw.get("schema_version")
            not in {CORPUS_MANIFEST_VERSION, CORPUS_MANIFEST_VERSION_V2}
            or not isinstance(raw.get("documents"), list)
            or not raw["documents"]
        ):
            raise ValueError("RAG corpus manifest contract is invalid")

        schema_version = str(raw["schema_version"])
        documents = tuple(
            cls._parse_document(candidate, schema_version)
            for candidate in raw["documents"]
        )
        declared_files = [item.source_file.casefold() for item in documents]
        declared_ids = [item.manual_id for item in documents]
        if (
            len(declared_files) != len(set(declared_files))
            or len(declared_ids) != len(set(declared_ids))
        ):
            raise ValueError("RAG corpus manifest contains duplicate identity")

        actual_files = cls._discover_sources(manuals_dir, schema_version)
        if sorted(item.source_file for item in documents) != actual_files:
            raise ValueError("RAG corpus manifest does not match the source directory")
        for item in documents:
            source = cls.source_path(manuals_dir, item)
            try:
                source_bytes = read_bounded_source_bytes(
                    source,
                    expected_suffix=PurePosixPath(item.source_file).suffix.lower(),
                )
            except ValueError as error:
                raise ValueError(
                    f"RAG corpus source validation failed: {error}"
                ) from error
            actual_sha256 = hashlib.sha256(source_bytes).hexdigest()
            if actual_sha256 != item.source_sha256:
                raise ValueError("RAG corpus source checksum does not match manifest")
        if not any(item.included for item in documents):
            raise ValueError("RAG corpus manifest has no included document")

        canonical = json.dumps(
            {
                "schema_version": schema_version,
                "documents": [
                    cls._canonical_document(item, schema_version)
                    for item in sorted(documents, key=lambda item: item.source_file)
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return cls(
            documents,
            hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            schema_version,
        )

    @staticmethod
    def source_path(manuals_dir: Path, document: CorpusManifestDocument) -> Path:
        """정규 상대 경로를 corpus 내부 절대 경로로 풀고 경로 탈출을 거부한다."""

        root = manuals_dir.resolve()
        source = (root / Path(*PurePosixPath(document.source_file).parts)).resolve()
        if source == root or root not in source.parents:
            raise ValueError("RAG corpus source escapes the configured directory")
        return source

    @classmethod
    def _parse_document(
        cls,
        candidate: object,
        schema_version: str,
    ) -> CorpusManifestDocument:
        if schema_version == CORPUS_MANIFEST_VERSION:
            expected_keys = {
                "source_file",
                "document_kind",
                "manual_id",
                "source_sha256",
            }
        else:
            expected_keys = {
                "source_file",
                "document_kind",
                "manual_id",
                "source_sha256",
                "source_version",
                "role_scope",
                "owner_team",
                "metadata",
            }
        if not isinstance(candidate, Mapping) or set(candidate) != expected_keys:
            raise ValueError("RAG corpus manifest document is invalid")

        source_file = candidate["source_file"]
        document_kind = candidate["document_kind"]
        manual_id = candidate["manual_id"]
        source_sha256 = candidate["source_sha256"]
        suffixes = {".pdf"} if schema_version == CORPUS_MANIFEST_VERSION else _SOURCE_SUFFIXES
        kinds = _DOCUMENT_KINDS_V1 if schema_version == CORPUS_MANIFEST_VERSION else _DOCUMENT_KINDS_V2
        if (
            not isinstance(source_file, str)
            or cls._normalized_relative_source(source_file) is None
            or PurePosixPath(source_file).suffix.lower() not in suffixes
            or document_kind not in kinds
            or not isinstance(manual_id, str)
            or _MANUAL_ID.fullmatch(manual_id) is None
            or not isinstance(source_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
        ):
            raise ValueError("RAG corpus manifest document is invalid")
        if schema_version == CORPUS_MANIFEST_VERSION:
            return CorpusManifestDocument(
                source_file=source_file,
                document_kind=str(document_kind),
                manual_id=manual_id,
                source_sha256=source_sha256,
            )

        source_version = candidate["source_version"]
        role_scope = candidate["role_scope"]
        owner_team = candidate["owner_team"]
        metadata = candidate["metadata"]
        if (
            not isinstance(source_version, str)
            or not 1 <= len(source_version.strip()) <= 100
            or not isinstance(role_scope, list)
            or not role_scope
            or len(role_scope) > 20
            or any(not isinstance(role, str) or _ROLE.fullmatch(role) is None for role in role_scope)
            or len(role_scope) != len(set(role_scope))
            or role_scope != sorted(role_scope)
            or not isinstance(owner_team, str)
            or not 1 <= len(owner_team.strip()) <= 100
            or not isinstance(metadata, Mapping)
            or set(metadata) != _METADATA_KEYS
            or any(value is not None and (not isinstance(value, str) or not 1 <= len(value.strip()) <= 100) for value in metadata.values())
        ):
            raise ValueError("RAG corpus manifest document is invalid")
        period = metadata["period"]
        department = metadata["department"]
        if document_kind == "INTERNAL_REPORT" and (
            period is None
            or department is None
            or source_version.strip().upper() == "UNRESOLVED"
        ):
            raise ValueError("RAG internal report metadata is incomplete")
        return CorpusManifestDocument(
            source_file=source_file,
            document_kind=str(document_kind),
            manual_id=manual_id,
            source_sha256=source_sha256,
            source_version=source_version.strip(),
            role_scope=tuple(role_scope),
            owner_team=owner_team.strip(),
            period=period.strip() if isinstance(period, str) else None,
            department=department.strip() if isinstance(department, str) else None,
        )

    @staticmethod
    def _normalized_relative_source(value: str) -> str | None:
        if (
            "\\" in value
            or not value
            or len(value) > 500
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
        ):
            return None
        source = PurePosixPath(value)
        if source.is_absolute() or any(part in {"", ".", ".."} for part in source.parts):
            return None
        normalized = source.as_posix()
        return normalized if normalized == value else None

    @staticmethod
    def _discover_sources(manuals_dir: Path, schema_version: str) -> list[str]:
        try:
            if schema_version == CORPUS_MANIFEST_VERSION:
                candidates = manuals_dir.glob("*.pdf")
            else:
                candidates = manuals_dir.rglob("*")
            return sorted(
                path.relative_to(manuals_dir).as_posix()
                for path in candidates
                if path.is_file() and path.suffix.lower() in _SOURCE_SUFFIXES
            )
        except OSError as error:
            raise ValueError("RAG corpus source directory is unreadable") from error

    @staticmethod
    def _canonical_document(
        item: CorpusManifestDocument,
        schema_version: str,
    ) -> dict[str, object]:
        document: dict[str, object] = {
            "source_file": item.source_file,
            "document_kind": item.document_kind,
            "manual_id": item.manual_id,
            "source_sha256": item.source_sha256,
        }
        if schema_version == CORPUS_MANIFEST_VERSION_V2:
            document.update(
                {
                    "source_version": item.source_version,
                    "role_scope": list(item.role_scope or ()),
                    "owner_team": item.owner_team,
                    "metadata": {
                        "period": item.period,
                        "department": item.department,
                    },
                }
            )
        return document

    def validate_access_policy(self, known_roles: frozenset[str]) -> None:
        """v2 검색 대상의 모든 역할이 활성 정책에 명시됐는지 검증한다."""

        if self.schema_version != CORPUS_MANIFEST_VERSION_V2:
            return
        for item in self.included_documents:
            roles = frozenset(item.role_scope or ())
            if not roles or not roles.issubset(known_roles):
                raise ValueError("RAG corpus role scope is not registered in access policy")

    @property
    def included_documents(self) -> tuple[CorpusManifestDocument, ...]:
        """REFERENCE를 제외한 결정론적 적재 대상 문서 tuple을 반환한다."""

        return tuple(item for item in self.documents if item.included)

    @property
    def included_document_checksums(self) -> dict[str, str]:
        """release 완전성 검증용 문서 ID와 원본 SHA-256 map을 반환한다."""

        return {
            item.manual_id: item.source_sha256
            for item in self.included_documents
        }

    @staticmethod
    def validate_parsed_document(
        expected: CorpusManifestDocument,
        parsed_manual_id: str,
        parsed_source_sha256: str,
    ) -> None:
        """parser 결과 식별자·checksum이 manifest 선언과 다르면 적재를 중단한다."""

        if (
            parsed_manual_id != expected.manual_id
            or parsed_source_sha256 != expected.source_sha256
        ):
            raise ValueError(
                "RAG parsed document identity or checksum does not match the corpus manifest"
            )
