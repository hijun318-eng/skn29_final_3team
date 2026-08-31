from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


CORPUS_MANIFEST_VERSION = "RagCorpusManifest.v1"
_DOCUMENT_KINDS = frozenset({"MANUAL", "REFERENCE"})
_MANUAL_ID = re.compile(r"^[A-Z][A-Z0-9-]{2,99}$")


@dataclass(frozen=True)
class CorpusManifestDocument:
    source_file: str
    document_kind: str
    manual_id: str
    source_sha256: str

    @property
    def included(self) -> bool:
        return self.document_kind == "MANUAL"


@dataclass(frozen=True)
class CorpusManifest:
    documents: tuple[CorpusManifestDocument, ...]
    manifest_sha256: str

    @classmethod
    def load(cls, path: Path, manuals_dir: Path) -> "CorpusManifest":
        """Load a closed manifest and require it to enumerate the PDF directory exactly."""

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("RAG corpus manifest is unreadable") from error
        if (
            not isinstance(raw, dict)
            or set(raw) != {"schema_version", "documents"}
            or raw.get("schema_version") != CORPUS_MANIFEST_VERSION
            or not isinstance(raw.get("documents"), list)
            or not raw["documents"]
        ):
            raise ValueError("RAG corpus manifest contract is invalid")

        documents: list[CorpusManifestDocument] = []
        for candidate in raw["documents"]:
            if not isinstance(candidate, dict) or set(candidate) != {
                "source_file",
                "document_kind",
                "manual_id",
                "source_sha256",
            }:
                raise ValueError("RAG corpus manifest document is invalid")
            source_file = candidate["source_file"]
            document_kind = candidate["document_kind"]
            manual_id = candidate["manual_id"]
            source_sha256 = candidate["source_sha256"]
            if (
                not isinstance(source_file, str)
                or not source_file.strip()
                or Path(source_file).name != source_file
                or Path(source_file).suffix.lower() != ".pdf"
                or document_kind not in _DOCUMENT_KINDS
                or not isinstance(manual_id, str)
                or _MANUAL_ID.fullmatch(manual_id) is None
                or not isinstance(source_sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
            ):
                raise ValueError("RAG corpus manifest document is invalid")
            documents.append(
                CorpusManifestDocument(
                    source_file=source_file,
                    document_kind=document_kind,
                    manual_id=manual_id,
                    source_sha256=source_sha256,
                )
            )

        declared_files = [item.source_file for item in documents]
        declared_ids = [item.manual_id for item in documents]
        if (
            len(declared_files) != len(set(declared_files))
            or len(declared_ids) != len(set(declared_ids))
        ):
            raise ValueError("RAG corpus manifest contains duplicate identity")
        actual_files = sorted(item.name for item in manuals_dir.glob("*.pdf"))
        if sorted(declared_files) != actual_files:
            raise ValueError("RAG corpus manifest does not match the PDF directory")
        for item in documents:
            try:
                actual_sha256 = hashlib.sha256(
                    (manuals_dir / item.source_file).read_bytes()
                ).hexdigest()
            except OSError as error:
                raise ValueError("RAG corpus source is unreadable") from error
            if actual_sha256 != item.source_sha256:
                raise ValueError("RAG corpus source checksum does not match manifest")
        if not any(item.included for item in documents):
            raise ValueError("RAG corpus manifest has no included manual")
        canonical = json.dumps(
            {
                "schema_version": CORPUS_MANIFEST_VERSION,
                "documents": [
                    {
                        "source_file": item.source_file,
                        "document_kind": item.document_kind,
                        "manual_id": item.manual_id,
                        "source_sha256": item.source_sha256,
                    }
                    for item in sorted(documents, key=lambda item: item.source_file)
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return cls(
            tuple(documents),
            hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )

    @property
    def included_documents(self) -> tuple[CorpusManifestDocument, ...]:
        return tuple(item for item in self.documents if item.included)

    @property
    def included_document_checksums(self) -> dict[str, str]:
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
        if (
            parsed_manual_id != expected.manual_id
            or parsed_source_sha256 != expected.source_sha256
        ):
            raise ValueError(
                "RAG parsed manual identity or checksum does not match the corpus manifest"
            )
