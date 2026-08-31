from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

import numpy as np
import pytest

from src.rag.corpus_manifest import (
    CORPUS_MANIFEST_VERSION,
    CorpusManifest,
    CorpusManifestDocument,
)
from src.rag.evidence_repository import RagEvidenceRepository
from src.rag.backup_validation import PgBackupRestoreValidator
from src.rag.pdf_ingestion import PdfManualParser
from src.rag.processing_profile import processing_profile_sha256
from src.rag.pgvector_repository import PgVectorRepository
from src.rag.vector_application import VectorRagApplication
from src.rag.vector_models import PdfChunk, PdfDocument


EMBEDDING = {
    "provider": "test",
    "model": "test-model",
    "dimensions": 2,
    "version": "test-model:d2",
}
MANIFEST_SHA256 = "a" * 64
PROCESSING_SHA256 = "e" * 64
EXPECTED_DOCUMENTS = {"MANUAL-ONE": "b" * 64}


class _Result:
    def __init__(
        self,
        row: tuple[object, ...] | None = None,
        rows: list[tuple[object, ...]] | None = None,
        rowcount: int = 1,
    ) -> None:
        self._row = row
        self._rows = rows or []
        self.rowcount = rowcount

    def fetchone(self) -> tuple[object, ...] | None:
        return self._row

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows


class _Connection:
    def __init__(self, responses: list[_Result]) -> None:
        self._responses = list(responses)
        self.statements: list[tuple[str, object]] = []
        self.rolled_back = False

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, error_type: object, *_args: object) -> None:
        self.rolled_back = error_type is not None

    def execute(self, sql: str, params: object = ()) -> _Result:
        self.statements.append((sql, params))
        if not self._responses:
            raise AssertionError(f"Unexpected SQL: {sql}")
        return self._responses.pop(0)


class _MigrationConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def __enter__(self) -> "_MigrationConnection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str) -> _Result:
        self.statements.append(sql)
        return _Result()


def _document(
    manual_id: str = "MANUAL-ONE",
    checksum: str = "b" * 64,
) -> PdfDocument:
    return PdfDocument(
        manual_id=manual_id,
        title="Manual one",
        version="1.0",
        source_path=f"/manuals/{manual_id}.pdf",
        checksum=checksum,
        role_scope=("STAFF",),
    )


def _chunk(manual_id: str = "MANUAL-ONE") -> PdfChunk:
    return PdfChunk(
        chunk_id=f"{manual_id}-chunk-1",
        manual_id=manual_id,
        page_start=1,
        page_end=1,
        section_title="Section",
        content="Approved manual content",
        checksum="c" * 64,
        token_count=3,
    )


def _backup_settings(tmp_path: Path, database_url: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        backup_dir=tmp_path / "backups",
        evidence_dir=tmp_path / "evidence",
        database_url=(
            database_url
            or "postgresql://custom_user:password@rag-postgres/custom_rag"
        ),
        corpus_manifest_path=tmp_path / "corpus_manifest.json",
        manuals_dir=tmp_path / "manuals",
        embedding_provider=EMBEDDING["provider"],
        model_id=EMBEDDING["model"],
        dimension=EMBEDDING["dimensions"],
        model_revision=EMBEDDING["version"],
        chunk_max_tokens=384,
        chunk_overlap_tokens=64,
    )


def _backup_manifest() -> SimpleNamespace:
    return SimpleNamespace(
        manifest_sha256=MANIFEST_SHA256,
        included_document_checksums=EXPECTED_DOCUMENTS,
    )


def _backup_receipt(validator: PgBackupRestoreValidator) -> dict[str, object]:
    return {
        "release_id": str(uuid4()),
        "status": "ACTIVE",
        "embedding_provider": EMBEDDING["provider"],
        "embedding_model": EMBEDDING["model"],
        "embedding_dimensions": EMBEDDING["dimensions"],
        "embedding_version": EMBEDDING["version"],
        "corpus_manifest_sha256": MANIFEST_SHA256,
        "processing_profile_sha256": (
            validator._expected_processing_profile_sha256
        ),
        "stored_documents": 1,
        "documents": 1,
        "deleted_documents": 0,
        "stored_chunks": 2,
        "chunks": 2,
        "deleted_chunks": 0,
        "embedding_metadata_mismatches": 0,
        "documents_without_chunks": 0,
        "successful_ingestion_runs": 1,
        "document_checksums": EXPECTED_DOCUMENTS,
        "approved_document_count": 1,
    }


def test_manifest_uses_document_kind_and_has_order_stable_hash(
    tmp_path: Path,
) -> None:
    manuals = tmp_path / "manuals"
    manuals.mkdir()
    source_bytes = {
        "00_combined_reference_name.pdf": b"manual-pdf",
        "ordinary.pdf": b"reference-pdf",
    }
    for filename, content in source_bytes.items():
        (manuals / filename).write_bytes(content)
    documents = [
        {
            "source_file": "ordinary.pdf",
            "document_kind": "REFERENCE",
            "manual_id": "REFERENCE-ONE",
            "source_sha256": hashlib.sha256(
                source_bytes["ordinary.pdf"]
            ).hexdigest(),
        },
        {
            "source_file": "00_combined_reference_name.pdf",
            "document_kind": "MANUAL",
            "manual_id": "MANUAL-ONE",
            "source_sha256": hashlib.sha256(
                source_bytes["00_combined_reference_name.pdf"]
            ).hexdigest(),
        },
    ]
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    first_path.write_text(
        json.dumps(
            {"schema_version": CORPUS_MANIFEST_VERSION, "documents": documents}
        ),
        encoding="utf-8",
    )
    second_path.write_text(
        json.dumps(
            {
                "schema_version": CORPUS_MANIFEST_VERSION,
                "documents": list(reversed(documents)),
            }
        ),
        encoding="utf-8",
    )

    first = CorpusManifest.load(first_path, manuals)
    second = CorpusManifest.load(second_path, manuals)

    assert [item.source_file for item in first.included_documents] == [
        "00_combined_reference_name.pdf"
    ]
    assert first.manifest_sha256 == second.manifest_sha256

    (manuals / "ordinary.pdf").write_bytes(b"replacement")
    with pytest.raises(ValueError, match="checksum does not match"):
        CorpusManifest.load(first_path, manuals)
    replacement_documents = [dict(item) for item in documents]
    replacement_documents[0]["source_sha256"] = hashlib.sha256(
        b"replacement"
    ).hexdigest()
    replacement_path = tmp_path / "replacement.json"
    replacement_path.write_text(
        json.dumps(
            {
                "schema_version": CORPUS_MANIFEST_VERSION,
                "documents": replacement_documents,
            }
        ),
        encoding="utf-8",
    )
    assert (
        CorpusManifest.load(replacement_path, manuals).manifest_sha256
        != first.manifest_sha256
    )
    (manuals / "ordinary.pdf").write_bytes(source_bytes["ordinary.pdf"])
    (manuals / "unlisted.pdf").write_bytes(b"pdf")
    with pytest.raises(ValueError, match="does not match"):
        CorpusManifest.load(first_path, manuals)


def test_pdf_parser_extracts_pages_from_the_initial_immutable_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[dict[str, object]] = []

    class Page:
        @staticmethod
        def get_text(_mode: str, *, sort: bool):
            assert sort is True
            return [(0, 0, 1, 1, "approved text", 0, 0)]

    class Document:
        def __enter__(self) -> "Document":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def __iter__(self):
            return iter([Page()])

    class Fitz:
        @staticmethod
        def open(*args: object, **kwargs: object) -> Document:
            assert args == ()
            opened.append(kwargs)
            return Document()

    monkeypatch.setitem(sys.modules, "fitz", Fitz)
    parser = object.__new__(PdfManualParser)

    assert parser._extract_pages(b"immutable-pdf-bytes") == [
        (1, ["approved text"])
    ]
    assert opened == [
        {"stream": b"immutable-pdf-bytes", "filetype": "pdf"}
    ]


def test_pdf_parser_reads_source_once_and_checksums_the_parsed_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_bytes = b"single immutable source"

    class Source:
        name = "POL-TEST-001_v1.0.pdf"
        stem = "POL-TEST-001_v1.0"
        reads = 0

        def read_bytes(self) -> bytes:
            self.reads += 1
            return source_bytes

        @staticmethod
        def resolve() -> Path:
            return Path("/manuals/POL-TEST-001_v1.0.pdf")

    class Chunker:
        schema_version = "test-profile"
        provider = SimpleNamespace(model_id="test-model")

        @staticmethod
        def chunk_blocks(
            manual_id: str, _page: int, _blocks: list[str]
        ) -> list[PdfChunk]:
            return [_chunk(manual_id)]

    source = Source()
    parser = PdfManualParser(Chunker())  # type: ignore[arg-type]
    captured: list[bytes] = []

    def extract(initial_bytes: bytes) -> list[tuple[int, list[str]]]:
        captured.append(initial_bytes)
        return [(1, ["POL-TEST-001 v1.0 approved text"])]

    monkeypatch.setattr(parser, "_extract_pages", extract)

    document, _chunks, _warnings, _inspection = parser.parse(source)  # type: ignore[arg-type]

    assert source.reads == 1
    assert captured == [source_bytes]
    assert document.checksum == hashlib.sha256(source_bytes).hexdigest()


def test_partial_ingest_is_rejected_before_any_runtime_dependency() -> None:
    application = object.__new__(VectorRagApplication)

    with pytest.raises(ValueError, match="Partial RAG ingestion"):
        application.ingest(limit=1)


def test_processing_profile_binds_chunk_limits_and_is_deterministic() -> None:
    baseline = processing_profile_sha256(384, 64)

    assert baseline == processing_profile_sha256(384, 64)
    assert baseline != processing_profile_sha256(385, 64)
    assert baseline != processing_profile_sha256(384, 63)
    with pytest.raises(ValueError, match="limits are invalid"):
        processing_profile_sha256(64, 64)


def test_mid_ingest_content_replacement_never_publishes_active_pointer() -> None:
    entries = (
        CorpusManifestDocument("one.pdf", "MANUAL", "MANUAL-ONE", "b" * 64),
        CorpusManifestDocument("two.pdf", "MANUAL", "MANUAL-TWO", "d" * 64),
    )
    manifest = CorpusManifest(entries, MANIFEST_SHA256)

    class Repository:
        active_pointer = "previous-release"
        published = False
        failed: tuple[object, ...] | None = None

        def start_run(self, *_args: object) -> None:
            return None

        def unchanged(self, *_args: object) -> bool:
            return False

        def stage_document(self, *_args: object) -> int:
            return 1

        def publish_release(self, *_args: object, **_kwargs: object) -> dict[str, object]:
            self.published = True
            self.active_pointer = "new-release"
            return {}

        def finish_run(self, *args: object) -> None:
            self.failed = args

    class Embedding:
        device = "cpu"

        @staticmethod
        def embed_documents(_texts: list[str], _batch_size: int) -> np.ndarray:
            return np.asarray([[0.1, 0.2]], dtype=np.float32)

    class Chunker:
        def __init__(self, **_kwargs: object) -> None:
            return None

    class Parser:
        def __init__(self, **_kwargs: object) -> None:
            return None

        def parse(self, path: Path):
            if path.name == "two.pdf":
                return (
                    _document("MANUAL-TWO", "d" * 64),
                    [_chunk("MANUAL-TWO")],
                    [],
                    {},
                )
            return _document("MANUAL-ONE"), [_chunk("MANUAL-ONE")], [], {}

    application = object.__new__(VectorRagApplication)
    application._settings = SimpleNamespace(  # type: ignore[attr-defined]
        corpus_manifest_path=Path("manifest.json"),
        manuals_dir=Path("manuals"),
        chunk_max_tokens=10,
        chunk_overlap_tokens=1,
        batch_size=1,
        embedding_provider=EMBEDDING["provider"],
        model_id=EMBEDDING["model"],
        dimension=EMBEDDING["dimensions"],
        model_revision=EMBEDDING["version"],
    )
    application._corpus_manifest = manifest  # type: ignore[attr-defined]
    application._processing_profile_sha256 = PROCESSING_SHA256  # type: ignore[attr-defined]
    repository = Repository()
    application._repository = repository  # type: ignore[attr-defined]
    embedding = Embedding()
    application._get_embedding = lambda: embedding  # type: ignore[method-assign]

    with (
        patch(
            "src.rag.vector_application.CorpusManifest.load",
            side_effect=[
                manifest,
                ValueError("RAG corpus source checksum does not match manifest"),
            ],
        ),
        patch("src.rag.token_chunker.TokenChunker", Chunker),
        patch("src.rag.vector_application.PdfManualParser", Parser),
        pytest.raises(ValueError, match="source checksum"),
    ):
        application.ingest()

    assert repository.published is False
    assert repository.active_pointer == "previous-release"
    assert repository.failed is not None
    assert repository.failed[1] == "FAILED"


def test_one_changed_source_copies_unchanged_document_and_stages_changed_one() -> None:
    entries = (
        CorpusManifestDocument("one.pdf", "MANUAL", "MANUAL-ONE", "b" * 64),
        CorpusManifestDocument("two.pdf", "MANUAL", "MANUAL-TWO", "d" * 64),
    )
    manifest = CorpusManifest(entries, MANIFEST_SHA256)

    class Repository:
        copied: list[str] = []
        staged: list[str] = []
        published: dict[str, object] | None = None

        def start_run(self, *_args: object) -> None:
            return None

        def unchanged(self, document: PdfDocument, *_args: object) -> bool:
            return document.manual_id == "MANUAL-ONE"

        def copy_active_document(
            self, _release_id: object, document: PdfDocument, *_args: object
        ) -> int:
            self.copied.append(document.manual_id)
            return 2

        def stage_document(
            self, _release_id: object, document: PdfDocument, *_args: object
        ) -> int:
            self.staged.append(document.manual_id)
            return 1

        def publish_release(self, *_args: object, **kwargs: object) -> dict[str, object]:
            self.published = kwargs
            return {"release_id": str(uuid4())}

        def finish_run(self, *_args: object) -> None:
            raise AssertionError("successful ingest must not fail the release")

    class Embedding:
        device = "cpu"
        calls: list[list[str]] = []

        def embed_documents(self, texts: list[str], _batch_size: int) -> np.ndarray:
            self.calls.append(texts)
            return np.asarray([[0.1, 0.2]], dtype=np.float32)

    class Chunker:
        def __init__(self, **_kwargs: object) -> None:
            return None

    class Parser:
        def __init__(self, **_kwargs: object) -> None:
            return None

        def parse(self, path: Path):
            if path.name == "one.pdf":
                return _document("MANUAL-ONE"), [_chunk("MANUAL-ONE")], [], {}
            return (
                _document("MANUAL-TWO", "d" * 64),
                [_chunk("MANUAL-TWO")],
                [],
                {},
            )

    application = object.__new__(VectorRagApplication)
    application._settings = SimpleNamespace(  # type: ignore[attr-defined]
        corpus_manifest_path=Path("manifest.json"),
        manuals_dir=Path("manuals"),
        chunk_max_tokens=10,
        chunk_overlap_tokens=1,
        batch_size=1,
        embedding_provider=EMBEDDING["provider"],
        model_id=EMBEDDING["model"],
        dimension=EMBEDDING["dimensions"],
        model_revision=EMBEDDING["version"],
    )
    application._corpus_manifest = manifest  # type: ignore[attr-defined]
    application._processing_profile_sha256 = PROCESSING_SHA256  # type: ignore[attr-defined]
    repository = Repository()
    application._repository = repository  # type: ignore[attr-defined]
    embedding = Embedding()
    application._get_embedding = lambda: embedding  # type: ignore[method-assign]
    application._write_evidence = lambda *_args: None  # type: ignore[method-assign]

    with (
        patch("src.rag.vector_application.CorpusManifest.load", return_value=manifest),
        patch("src.rag.token_chunker.TokenChunker", Chunker),
        patch("src.rag.vector_application.PdfManualParser", Parser),
    ):
        report = application.ingest()

    assert repository.copied == ["MANUAL-ONE"]
    assert repository.staged == ["MANUAL-TWO"]
    assert embedding.calls == [["Approved manual content"]]
    assert repository.published is not None
    assert repository.published["expected_document_count"] == 2
    assert repository.published["expected_chunk_count"] == 3
    assert repository.published["processing_profile_sha256"] == PROCESSING_SHA256
    assert report["skipped_unchanged_documents"] == 1
    assert report["processed_documents"] == 1


def test_vector_search_requires_exact_active_receipt_before_embedding() -> None:
    class Repository:
        @staticmethod
        def active_release_receipt(*_args: object) -> None:
            return None

    application = object.__new__(VectorRagApplication)
    application._settings = SimpleNamespace(  # type: ignore[attr-defined]
        embedding_provider=EMBEDDING["provider"],
        model_id=EMBEDDING["model"],
        dimension=EMBEDDING["dimensions"],
        model_revision=EMBEDDING["version"],
    )
    application._corpus_manifest = SimpleNamespace(  # type: ignore[attr-defined]
        manifest_sha256=MANIFEST_SHA256
    )
    application._processing_profile_sha256 = PROCESSING_SHA256  # type: ignore[attr-defined]
    application._repository = Repository()  # type: ignore[attr-defined]
    embedding_calls: list[str] = []
    application._get_embedding = lambda: embedding_calls.append("called")  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="Active RAG corpus release"):
        application.search("question", "STAFF", actor_hash="c" * 64)

    assert embedding_calls == []


def test_copy_reuses_only_same_content_and_profile_into_new_manifest_release() -> None:
    source_release = uuid4()
    target_release = uuid4()
    connection = _Connection(
        [
            _Result((source_release,)),
            _Result((1,)),
            _Result(
                (
                    "Manual one",
                    "1.0",
                    "/manuals/MANUAL-ONE.pdf",
                    "b" * 64,
                    None,
                )
            ),
            _Result(
                rows=[
                    (
                        "chunk-1",
                        None,
                        EMBEDDING["provider"],
                        EMBEDDING["model"],
                        EMBEDDING["dimensions"],
                        EMBEDDING["version"],
                        "b" * 64,
                    )
                ]
            ),
            _Result(("MANUAL-ONE",)),
            _Result(rows=[("chunk-1",)]),
        ]
    )
    repository = PgVectorRepository(
        "postgresql://test",
        EMBEDDING,
        MANIFEST_SHA256,
        EXPECTED_DOCUMENTS,
        PROCESSING_SHA256,
    )

    with patch(
        "src.rag.pgvector_repository.psycopg.connect", return_value=connection
    ):
        copied = repository.copy_active_document(
            target_release,
            _document(),
            EMBEDDING,
            PROCESSING_SHA256,
        )

    assert copied == 1
    source_sql, source_params = connection.statements[0]
    target_sql, target_params = connection.statements[1]
    source_document_sql, _source_document_params = connection.statements[2]
    source_chunks_sql, _source_chunks_params = connection.statements[3]
    document_sql, _document_params = connection.statements[4]
    copied_chunks_sql, _copied_chunks_params = connection.statements[5]
    assert "FOR SHARE OF active, release" in source_sql
    assert "processing_profile_sha256=%s" in source_sql
    assert "corpus_manifest_sha256" not in source_sql
    assert source_params[-1] == PROCESSING_SHA256
    assert "status='STAGING'" in target_sql
    assert "corpus_manifest_sha256=%s" in target_sql
    assert "processing_profile_sha256=%s" in target_sql
    assert target_params[-2:] == (MANIFEST_SHA256, PROCESSING_SHA256)
    assert "FOR UPDATE" in source_document_sql
    assert "FOR SHARE" in source_chunks_sql
    assert "d.approval_status" in document_sql
    assert "d.deleted_at IS NULL" in document_sql
    assert "c.deleted_at IS NULL" not in copied_chunks_sql


@pytest.mark.parametrize(
    "source_chunk",
    [
        (
            "chunk-1",
            "deleted",
            EMBEDDING["provider"],
            EMBEDDING["model"],
            EMBEDDING["dimensions"],
            EMBEDDING["version"],
            "b" * 64,
        ),
        (
            "chunk-1",
            None,
            "drifted-provider",
            EMBEDDING["model"],
            EMBEDDING["dimensions"],
            EMBEDDING["version"],
            "b" * 64,
        ),
        (
            "chunk-1",
            None,
            EMBEDDING["provider"],
            EMBEDDING["model"],
            EMBEDDING["dimensions"],
            EMBEDDING["version"],
            "d" * 64,
        ),
    ],
    ids=["deleted", "embedding-metadata-drift", "source-hash-drift"],
)
def test_copy_rejects_any_deleted_or_drifted_source_chunk(
    source_chunk: tuple[object, ...],
) -> None:
    source_release = uuid4()
    target_release = uuid4()
    connection = _Connection(
        [
            _Result((source_release,)),
            _Result((1,)),
            _Result(
                (
                    "Manual one",
                    "1.0",
                    "/manuals/MANUAL-ONE.pdf",
                    "b" * 64,
                    None,
                )
            ),
            _Result(rows=[source_chunk]),
        ]
    )
    repository = PgVectorRepository(
        "postgresql://test",
        EMBEDDING,
        MANIFEST_SHA256,
        EXPECTED_DOCUMENTS,
        PROCESSING_SHA256,
    )

    with (
        patch(
            "src.rag.pgvector_repository.psycopg.connect",
            return_value=connection,
        ),
        pytest.raises(RuntimeError, match="chunks are incomplete or drifted"),
    ):
        repository.copy_active_document(
            target_release,
            _document(),
            EMBEDDING,
            PROCESSING_SHA256,
        )

    assert connection.rolled_back is True
    assert len(connection.statements) == 4
    assert "FOR UPDATE" in connection.statements[2][0]
    assert "FOR SHARE" in connection.statements[3][0]


def test_copy_rejects_deleted_source_document_before_approval_inheritance() -> None:
    source_release = uuid4()
    target_release = uuid4()
    connection = _Connection(
        [
            _Result((source_release,)),
            _Result((1,)),
            _Result(
                (
                    "Manual one",
                    "1.0",
                    "/manuals/MANUAL-ONE.pdf",
                    "b" * 64,
                    "deleted",
                )
            ),
        ]
    )
    repository = PgVectorRepository(
        "postgresql://test",
        EMBEDDING,
        MANIFEST_SHA256,
        EXPECTED_DOCUMENTS,
        PROCESSING_SHA256,
    )

    with (
        patch(
            "src.rag.pgvector_repository.psycopg.connect",
            return_value=connection,
        ),
        pytest.raises(RuntimeError, match="document changed"),
    ):
        repository.copy_active_document(
            target_release,
            _document(),
            EMBEDDING,
            PROCESSING_SHA256,
        )

    assert connection.rolled_back is True
    assert len(connection.statements) == 3
    assert "FOR UPDATE" in connection.statements[2][0]


def test_stage_rejects_document_content_outside_manifest_receipt() -> None:
    repository = PgVectorRepository(
        "postgresql://test",
        EMBEDDING,
        MANIFEST_SHA256,
        EXPECTED_DOCUMENTS,
        PROCESSING_SHA256,
    )

    with pytest.raises(ValueError, match="differs from corpus manifest"):
        repository.stage_document(
            uuid4(),
            _document(checksum="d" * 64),
            [_chunk()],
            np.asarray([[0.1, 0.2]], dtype=np.float32),
            EMBEDDING,
        )


def test_publish_validates_both_receipts_and_checks_every_mutation_rowcount() -> None:
    previous_release = uuid4()
    release_id = uuid4()
    connection = _Connection(
        [
            _Result((previous_release,)),
            _Result(("STAGING", 1, 0, 2, 0, 0, 0, 1, EXPECTED_DOCUMENTS)),
            _Result(("ACTIVE", 1, 1, 0, 2, 2, 0, 0, 0, 1)),
            _Result(rowcount=1),
            _Result(rowcount=1),
            _Result(rowcount=1),
            _Result(rowcount=1),
        ]
    )
    repository = PgVectorRepository(
        "postgresql://test",
        EMBEDDING,
        MANIFEST_SHA256,
        EXPECTED_DOCUMENTS,
        PROCESSING_SHA256,
    )

    with patch(
        "src.rag.pgvector_repository.psycopg.connect", return_value=connection
    ):
        receipt = repository.publish_release(
            release_id,
            expected_document_count=1,
            expected_chunk_count=2,
            metadata=EMBEDDING,
            corpus_manifest_sha256=MANIFEST_SHA256,
            processing_profile_sha256=PROCESSING_SHA256,
        )

    assert receipt["release_id"] == str(release_id)
    assert receipt["previous_release_id"] == str(previous_release)
    sql = [statement for statement, _params in connection.statements]
    assert "FOR UPDATE" in sql[0]
    assert "d.deleted_at IS NOT NULL" in sql[1]
    assert "c.deleted_at IS NOT NULL" in sql[1]
    assert "status='ACTIVE'" in sql[3]
    assert "status='STAGING'" in sql[4]
    assert "WHERE singleton=TRUE" in sql[5]
    assert "status='RUNNING'" in sql[6]


def test_start_and_publish_reject_runtime_manifest_or_profile_drift() -> None:
    repository = PgVectorRepository(
        "postgresql://test",
        EMBEDDING,
        MANIFEST_SHA256,
        EXPECTED_DOCUMENTS,
        PROCESSING_SHA256,
    )

    with pytest.raises(ValueError, match="manifest hash differs"):
        repository.start_run(
            uuid4(),
            EMBEDDING,
            "f" * 64,
            PROCESSING_SHA256,
        )
    with pytest.raises(ValueError, match="processing profile differs"):
        repository.publish_release(
            uuid4(),
            expected_document_count=1,
            expected_chunk_count=1,
            metadata=EMBEDDING,
            corpus_manifest_sha256=MANIFEST_SHA256,
            processing_profile_sha256="f" * 64,
        )


def test_publish_rejects_deleted_staging_rows_before_any_mutation() -> None:
    connection = _Connection(
        [
            _Result((None,)),
            _Result(("STAGING", 1, 1, 2, 0, 0, 0, 1, EXPECTED_DOCUMENTS)),
        ]
    )
    repository = PgVectorRepository(
        "postgresql://test",
        EMBEDDING,
        MANIFEST_SHA256,
        EXPECTED_DOCUMENTS,
        PROCESSING_SHA256,
    )

    with (
        patch("src.rag.pgvector_repository.psycopg.connect", return_value=connection),
        pytest.raises(RuntimeError, match="incomplete or drifted"),
    ):
        repository.publish_release(
            uuid4(),
            expected_document_count=1,
            expected_chunk_count=2,
            metadata=EMBEDDING,
            corpus_manifest_sha256=MANIFEST_SHA256,
            processing_profile_sha256=PROCESSING_SHA256,
        )

    assert connection.rolled_back is True
    assert not any(
        statement.lstrip().upper().startswith("UPDATE ")
        for statement, _params in connection.statements
    )


def test_publish_rejects_any_staging_document_without_full_runtime_eligibility() -> None:
    connection = _Connection(
        [
            _Result((None,)),
            _Result(("STAGING", 1, 0, 2, 0, 0, 0, 0, EXPECTED_DOCUMENTS)),
        ]
    )
    repository = PgVectorRepository(
        "postgresql://test",
        EMBEDDING,
        MANIFEST_SHA256,
        EXPECTED_DOCUMENTS,
        PROCESSING_SHA256,
    )

    with (
        patch("src.rag.pgvector_repository.psycopg.connect", return_value=connection),
        pytest.raises(RuntimeError, match="incomplete or drifted"),
    ):
        repository.publish_release(
            uuid4(),
            expected_document_count=1,
            expected_chunk_count=2,
            metadata=EMBEDDING,
            corpus_manifest_sha256=MANIFEST_SHA256,
            processing_profile_sha256=PROCESSING_SHA256,
        )

    eligibility_sql = connection.statements[1][0]
    assert "approval_status='APPROVED'" in eligibility_sql
    assert "document_status='WORKING_KNOWLEDGE'" in eligibility_sql
    assert "validity_status!='UNRESOLVED'" in eligibility_sql
    assert "cardinality(d.role_scope)>0" in eligibility_sql
    assert "'STAFF'=ANY(d.role_scope)" in eligibility_sql
    assert "effective_from<=CURRENT_DATE" in eligibility_sql
    assert "expires_at>=CURRENT_DATE" in eligibility_sql
    assert connection.rolled_back is True


def test_finish_failed_release_requires_both_exact_row_updates() -> None:
    connection = _Connection([_Result(rowcount=1), _Result(rowcount=0)])
    repository = PgVectorRepository(
        "postgresql://test", EMBEDDING, MANIFEST_SHA256
    )

    with (
        patch("src.rag.pgvector_repository.psycopg.connect", return_value=connection),
        pytest.raises(RuntimeError, match="could not be finalized"),
    ):
        repository.finish_run(uuid4(), "FAILED", 1, 2, "failed")

    assert connection.rolled_back is True
    assert "status='RUNNING'" in connection.statements[0][0]
    assert "status='STAGING'" in connection.statements[1][0]


def test_active_receipt_rejects_deleted_or_metadata_drifted_storage() -> None:
    connection = _Connection([_Result(None)])
    repository = PgVectorRepository(
        "postgresql://test",
        EMBEDDING,
        MANIFEST_SHA256,
        EXPECTED_DOCUMENTS,
        PROCESSING_SHA256,
    )

    with patch(
        "src.rag.pgvector_repository.psycopg.connect", return_value=connection
    ):
        assert (
            repository.active_release_receipt(
                EMBEDDING, MANIFEST_SHA256, PROCESSING_SHA256
            )
            is None
        )

    sql = connection.statements[0][0]
    assert "release.document_count=(" in sql
    assert "release.chunk_count=(" in sql
    assert "release.document_count=(" in sql
    assert "'STAFF'=ANY(eligible.role_scope)" in sql
    assert "d.deleted_at IS NOT NULL" in sql
    assert "c.deleted_at IS NOT NULL" in sql
    assert "c.embedding_provider<>release.embedding_provider" in sql
    assert sql.count("eligible.document_status='WORKING_KNOWLEDGE'") == 3


def test_evidence_inventory_locks_and_reads_only_the_active_release() -> None:
    release_id = uuid4()
    connection = _Connection(
        [
            _Result((release_id,)),
            _Result(
                rows=[
                    (
                        "MANUAL-ONE",
                        "Manual one",
                        "1.0",
                        "/manuals/one.pdf",
                        "b" * 64,
                        2,
                        1,
                    )
                ]
            ),
        ]
    )
    repository = RagEvidenceRepository(
        "postgresql://test",
        EMBEDDING,
        MANIFEST_SHA256,
        EXPECTED_DOCUMENTS,
        PROCESSING_SHA256,
    )

    with patch("src.rag.evidence_repository.psycopg.connect", return_value=connection):
        inventory = repository.source_inventory()

    assert inventory[0]["manual_id"] == "MANUAL-ONE"
    assert "FOR SHARE OF active, release" in connection.statements[0][0]
    inventory_sql, inventory_params = connection.statements[1]
    assert "FROM corpus_release_documents" in inventory_sql
    assert "corpus_release_chunks" in inventory_sql
    assert "FROM documents" not in inventory_sql
    assert inventory_params == (release_id,)


def test_source_pdf_rejects_bytes_that_drifted_after_release_publish(
    tmp_path: Path,
) -> None:
    manuals = tmp_path / "manuals"
    manuals.mkdir()
    source = manuals / "manual.pdf"
    source.write_bytes(b"replacement bytes")

    class Repository:
        @staticmethod
        def active_release_receipt(*_args: object) -> dict[str, object]:
            return {"release_id": str(uuid4())}

        @staticmethod
        def source_receipt(*_args: object) -> tuple[Path, str]:
            return source, hashlib.sha256(b"published bytes").hexdigest()

    application = object.__new__(VectorRagApplication)
    application._settings = SimpleNamespace(  # type: ignore[attr-defined]
        embedding_provider=EMBEDDING["provider"],
        model_id=EMBEDDING["model"],
        dimension=EMBEDDING["dimensions"],
        model_revision=EMBEDDING["version"],
        manuals_dir=manuals,
    )
    application._corpus_manifest = SimpleNamespace(  # type: ignore[attr-defined]
        manifest_sha256=MANIFEST_SHA256
    )
    application._processing_profile_sha256 = PROCESSING_SHA256  # type: ignore[attr-defined]
    application._repository = Repository()  # type: ignore[attr-defined]
    application._policy = SimpleNamespace(  # type: ignore[attr-defined]
        decide=lambda _role, _top_k: SimpleNamespace(
            allow_unresolved_validity=False
        )
    )

    with pytest.raises(FileNotFoundError):
        application.source_pdf("MANUAL-ONE", "STAFF")


def test_backup_names_are_env_derived_unique_and_bounded(
    tmp_path: Path,
) -> None:
    fixed_id = UUID("00112233-4455-6677-8899-aabbccddeeff")
    settings = _backup_settings(tmp_path)
    with (
        patch.dict(
            "os.environ",
            {
                "RAG_DB_NAME": "custom_rag",
                "RAG_DB_USER": "custom_user",
                "RAG_DB_CONTAINER": "custom-rag-postgres",
                "RAG_BACKUP_CONTAINER_DIR": "/var/tmp/rag-backups",
            },
            clear=True,
        ),
        patch(
            "src.rag.backup_validation.VectorSettings.load",
            return_value=settings,
        ),
        patch(
            "src.rag.backup_validation.CorpusManifest.load",
            return_value=_backup_manifest(),
        ),
        patch("src.rag.backup_validation.uuid4", return_value=fixed_id),
    ):
        validator = PgBackupRestoreValidator(tmp_path)

    assert validator._source_database == "custom_rag"
    assert validator._database_user == "custom_user"
    assert validator._container == "custom-rag-postgres"
    assert validator._restore_database == (
        "custom_rag_restore_check_001122334455"
    )
    assert validator._restore_database != validator._source_database
    assert validator._container_backup == (
        "/var/tmp/rag-backups/"
        "rag_corpus_00112233445566778899aabbccddeeff.dump"
    )
    assert validator._container_restore_input == (
        "/var/tmp/rag-backups/"
        "rag_corpus_restore_00112233445566778899aabbccddeeff.dump"
    )


def test_backup_database_identity_must_match_runtime_url(tmp_path: Path) -> None:
    settings = _backup_settings(
        tmp_path,
        "postgresql://other_user:password@rag-postgres/other_rag",
    )
    with (
        patch.dict(
            "os.environ",
            {"RAG_DB_NAME": "custom_rag", "RAG_DB_USER": "custom_user"},
            clear=True,
        ),
        patch(
            "src.rag.backup_validation.VectorSettings.load",
            return_value=settings,
        ),
        pytest.raises(ValueError, match="must match"),
    ):
        PgBackupRestoreValidator(tmp_path)


def test_backup_restores_the_host_artifact_and_cleans_every_temporary_resource(
    tmp_path: Path,
) -> None:
    settings = _backup_settings(tmp_path)
    with (
        patch.dict(
            "os.environ",
            {
                "RAG_DB_NAME": "custom_rag",
                "RAG_DB_USER": "custom_user",
                "RAG_DB_CONTAINER": "custom-rag-postgres",
                "RAG_BACKUP_CONTAINER_DIR": "/var/tmp/rag-backups",
            },
            clear=True,
        ),
        patch(
            "src.rag.backup_validation.VectorSettings.load",
            return_value=settings,
        ),
        patch(
            "src.rag.backup_validation.CorpusManifest.load",
            return_value=_backup_manifest(),
        ),
    ):
        validator = PgBackupRestoreValidator(tmp_path)

    docker_calls: list[tuple[str, ...]] = []
    copy_calls: list[tuple[str, ...]] = []

    def fake_docker(*arguments: str) -> str:
        docker_calls.append(arguments)
        return ""

    def fake_run(command: list[str]) -> str:
        copy_calls.append(tuple(command))
        if command[:2] == ["docker", "cp"] and command[2].startswith(
            "custom-rag-postgres:"
        ):
            Path(command[3]).write_bytes(b"host-backup-artifact")
        return ""

    receipt = _backup_receipt(validator)
    validator._docker = fake_docker  # type: ignore[method-assign]
    validator._run = fake_run  # type: ignore[method-assign]
    validator._active_release_receipt = (  # type: ignore[method-assign]
        lambda _database: dict(receipt)
    )

    report = validator.validate()

    backup_path = settings.backup_dir / validator._backup_filename
    assert copy_calls == [
        (
            "docker", "cp",
            f"custom-rag-postgres:{validator._container_backup}",
            str(backup_path),
        ),
        (
            "docker", "cp", str(backup_path),
            f"custom-rag-postgres:{validator._container_restore_input}",
        ),
    ]
    restore = next(call for call in docker_calls if call[0] == "pg_restore")
    assert restore[-1] == validator._container_restore_input
    assert restore[-1] != validator._container_backup
    assert ("rm", "-f", "--", validator._container_backup) in docker_calls
    assert (
        "rm", "-f", "--", validator._container_restore_input
    ) in docker_calls
    assert report["status"] == "SUCCESS"
    assert report["cleanup"] == {
        "restore_database_removed": True,
        "container_dump_removed": True,
        "container_restore_input_removed": True,
    }


def test_backup_failure_still_cleans_all_resources_and_records_actual_state(
    tmp_path: Path,
) -> None:
    settings = _backup_settings(tmp_path)
    with (
        patch.dict(
            "os.environ",
            {"RAG_DB_NAME": "custom_rag", "RAG_DB_USER": "custom_user"},
            clear=True,
        ),
        patch(
            "src.rag.backup_validation.VectorSettings.load",
            return_value=settings,
        ),
        patch(
            "src.rag.backup_validation.CorpusManifest.load",
            return_value=_backup_manifest(),
        ),
    ):
        validator = PgBackupRestoreValidator(tmp_path)

    docker_calls: list[tuple[str, ...]] = []

    def fake_docker(*arguments: str) -> str:
        docker_calls.append(arguments)
        if arguments[0] == "pg_restore":
            raise RuntimeError("restore failed")
        if arguments[:3] == (
            "rm", "-f", "--"
        ) and arguments[-1] == validator._container_backup:
            raise RuntimeError("dump cleanup failed")
        return ""

    def fake_run(command: list[str]) -> str:
        if command[:2] == ["docker", "cp"] and command[2].startswith(
            f"{validator._container}:"
        ):
            Path(command[3]).write_bytes(b"host-backup-artifact")
        return ""

    validator._docker = fake_docker  # type: ignore[method-assign]
    validator._run = fake_run  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="restore failed"):
        validator.validate()

    assert ("rm", "-f", "--", validator._container_backup) in docker_calls
    assert (
        "rm", "-f", "--", validator._container_restore_input
    ) in docker_calls
    evidence = json.loads(
        (settings.evidence_dir / "backup_restore_validation.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["status"] == "FAILED"
    assert evidence["temporary_database_removed"] is True
    assert evidence["cleanup"] == {
        "restore_database_removed": True,
        "container_dump_removed": False,
        "container_restore_input_removed": True,
    }


def test_backup_active_receipt_must_match_runtime_release_contract(
    tmp_path: Path,
) -> None:
    settings = _backup_settings(tmp_path)
    with (
        patch.dict(
            "os.environ",
            {"RAG_DB_NAME": "custom_rag", "RAG_DB_USER": "custom_user"},
            clear=True,
        ),
        patch(
            "src.rag.backup_validation.VectorSettings.load",
            return_value=settings,
        ),
        patch(
            "src.rag.backup_validation.CorpusManifest.load",
            return_value=_backup_manifest(),
        ),
    ):
        validator = PgBackupRestoreValidator(tmp_path)

    receipt = _backup_receipt(validator)
    assert validator._valid_active_release(receipt) is True

    assert validator._valid_active_release(
        {**receipt, "corpus_manifest_sha256": "f" * 64}
    ) is False
    assert validator._valid_active_release(
        {**receipt, "processing_profile_sha256": "f" * 64}
    ) is False
    assert validator._valid_active_release(
        {**receipt, "embedding_model": "different-model"}
    ) is False
    assert validator._valid_active_release(
        {**receipt, "document_checksums": {"MANUAL-OTHER": "f" * 64}}
    ) is False
    assert validator._valid_active_release(
        {**receipt, "approved_document_count": 0}
    ) is False
    assert validator._valid_active_release(
        {**receipt, "approved_document_count": 2}
    ) is False


def test_backup_restore_target_guard_rejects_source_or_unbounded_names() -> None:
    with pytest.raises(ValueError, match="Unsafe restore database"):
        PgBackupRestoreValidator._assert_safe_restore_target("source", "source")
    with pytest.raises(ValueError, match="Unsafe restore database"):
        PgBackupRestoreValidator._assert_safe_restore_target(
            "source", "different_database"
        )


def test_release_migration_is_replayable_and_never_promotes_legacy_rows() -> None:
    migration = (
        Path(__file__).resolve().parents[2]
        / "infrastructure/rag/db/init/010_corpus_releases.sql"
    )
    sql = migration.read_text(encoding="utf-8")
    assert sql.count("CREATE TABLE IF NOT EXISTS") == 4
    assert "ADD COLUMN IF NOT EXISTS corpus_manifest_sha256" in sql
    assert "ADD COLUMN IF NOT EXISTS processing_profile_sha256" in sql
    assert "DROP CONSTRAINT IF EXISTS corpus_releases_manifest_sha256_check" in sql
    assert "corpus_releases_processing_profile_sha256_check" in sql
    assert "ON CONFLICT(singleton) DO NOTHING" in sql
    assert "INSERT INTO corpus_releases" not in sql
    assert "OLD.status = 'ACTIVE'" in sql
    assert "NEW.status <> 'RETIRED'" in sql
    assert "OLD.status = 'RETIRED'" in sql
    assert sql.count("BEFORE INSERT OR UPDATE OR DELETE") == 3
    assert "IF TG_OP = 'INSERT'" in sql
    assert sql.count("FOR UPDATE;") >= 2
    assert "corpus content cannot move between releases" in sql
    assert sql.count("guard_published_corpus_content_mutation()") == 3

    connection = _MigrationConnection()
    repository = PgVectorRepository("postgresql://test")
    with patch(
        "src.rag.pgvector_repository.psycopg.connect", return_value=connection
    ) as connect:
        repository.migrate(migration)
        repository.migrate(migration)

    assert connect.call_count == 2
    assert connect.call_args.kwargs == {"autocommit": True}
    assert connection.statements == [sql, sql]


def test_legacy_document_replacement_and_success_receipts_are_not_exposed() -> None:
    assert not hasattr(PgVectorRepository, "replace_document")
    with pytest.raises(RuntimeError, match="unsupported for immutable corpus releases"):
        object.__new__(VectorRagApplication).validate_lifecycle()

    root = Path(__file__).resolve().parents[2]
    backup_source = (root / "src/rag/backup_validation.py").read_text(
        encoding="utf-8"
    )
    assert "FROM corpus_active_release" in backup_source
    assert "FROM documents" not in backup_source
    assert "FROM document_chunks" not in backup_source


def test_search_audit_commits_release_bound_evidence_receipt_atomically() -> None:
    release_id = uuid4()
    request_id = uuid4()
    evidence = [
        {
            "evidence_id": "MANUAL-ONE:1.0:1:chunk-1",
            "text": "Approved manual content",
            "title": "Manual one",
            "manual_id": "MANUAL-ONE",
            "section_title": "Section",
            "citation": "[Manual one v1.0 p.1 Section]",
        }
    ]
    connection = _Connection(
        [
            _Result(rowcount=0),
            _Result((release_id,)),
            _Result(rowcount=1),
            _Result(rowcount=1),
            _Result(rowcount=1),
        ]
    )
    repository = PgVectorRepository(
        "postgresql://test",
        EMBEDDING,
        MANIFEST_SHA256,
        EXPECTED_DOCUMENTS,
        PROCESSING_SHA256,
    )

    with patch(
        "src.rag.pgvector_observability.psycopg.connect",
        return_value=connection,
    ):
        repository.audit_search(
            "d" * 64,
            "STAFF",
            1,
            2.5,
            request_id=str(request_id),
            trace_id="trace-rag-user-request",
            tool_code="internal-manual-search",
            tool_version="2.0.0",
            actor_hash="c" * 64,
            corpus_release_id=str(release_id),
            answer_query_sha256="f" * 64,
            answer_intent="REGULATION_CHECK",
            answer_evidence=evidence,
        )

    statements = [statement for statement, _params in connection.statements]
    assert "DELETE FROM retrieval_evidence_receipts" in statements[0]
    assert "FOR SHARE OF active, release" in statements[1]
    assert "INSERT INTO retrieval_evidence_receipts" in statements[2]
    assert "INSERT INTO retrieval_audit_logs" in statements[3]
    assert "INSERT INTO tool_runs" in statements[4]
    receipt_params = connection.statements[2][1]
    assert receipt_params[0] == request_id
    assert receipt_params[1] == release_id
    assert receipt_params[3] == "REGULATION_CHECK"
    assert receipt_params[4] == "trace-rag-user-request"
    assert receipt_params[5] == "c" * 64
    assert receipt_params[7] == [evidence[0]["evidence_id"]]


def test_answer_uses_only_exact_current_release_receipt_evidence() -> None:
    request_id = uuid4()
    evidence = [
        {
            "evidence_id": "MANUAL-ONE:1.0:1:chunk-1",
            "text": "Approved manual content",
            "title": "Manual one",
            "manual_id": "MANUAL-ONE",
            "section_title": "Section",
            "citation": "[Manual one v1.0 p.1 Section]",
        }
    ]
    canonical = json.dumps(
        evidence,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    connection = _Connection(
        [
            _Result(
                (
                    [evidence[0]["evidence_id"]],
                    evidence,
                    hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                )
            ),
            _Result(rows=[(1, "MANUAL-ONE", evidence[0]["evidence_id"])]),
            _Result(rowcount=1),
        ]
    )
    repository = PgVectorRepository(
        "postgresql://test",
        EMBEDDING,
        MANIFEST_SHA256,
        EXPECTED_DOCUMENTS,
        PROCESSING_SHA256,
    )

    with patch(
        "src.rag.pgvector_repository.psycopg.connect",
        return_value=connection,
    ):
        loaded = repository.load_answer_evidence(
            retrieval_request_id=str(request_id),
            role="STAFF",
            query="approved question",
            answer_intent="REGULATION_CHECK",
            trace_id=str(request_id),
            actor_hash="c" * 64,
            caller_evidence=evidence,
        )

    assert loaded == evidence
    sql, params = connection.statements[0]
    assert "JOIN corpus_active_release" in sql
    assert "release.status='ACTIVE'" in sql
    assert "receipt.consumed_at IS NULL" in sql
    assert "receipt.expires_at>CURRENT_TIMESTAMP" in sql
    assert "FOR UPDATE OF receipt" in sql
    assert "FOR SHARE OF active, release" in sql
    assert params[0] == request_id
    assert params[1] == "STAFF"
    assert params[2] == "REGULATION_CHECK"
    assert params[5] == hashlib.sha256(b"approved question").hexdigest()
    evidence_sql = connection.statements[1][0]
    assert "jsonb_array_elements" in evidence_sql
    assert "JOIN corpus_release_documents" in evidence_sql
    assert "JOIN corpus_release_chunks" in evidence_sql
    assert "document.approval_status='APPROVED'" in evidence_sql
    assert "document.validity_status!='UNRESOLVED'" in evidence_sql
    assert "FOR SHARE OF active, release, document, chunk" in evidence_sql
    assert "SET consumed_at=CURRENT_TIMESTAMP" in connection.statements[2][0]


def test_answer_rejects_retired_or_mismatched_retrieval_receipt() -> None:
    repository = PgVectorRepository(
        "postgresql://test",
        EMBEDDING,
        MANIFEST_SHA256,
        EXPECTED_DOCUMENTS,
        PROCESSING_SHA256,
    )
    connection = _Connection([_Result(None)])

    with (
        patch(
            "src.rag.pgvector_repository.psycopg.connect",
            return_value=connection,
        ),
        pytest.raises(RuntimeError, match="unavailable, expired, consumed, or unauthorized"),
    ):
        repository.load_answer_evidence(
            retrieval_request_id=str(uuid4()),
            role="STAFF",
            query="question",
            answer_intent="REGULATION_CHECK",
            trace_id="trace-rag-user-request",
            actor_hash="c" * 64,
            caller_evidence=[],
        )

    sql, params = connection.statements[0]
    assert "receipt.answer_intent=%s" in sql
    assert "receipt.trace_id=%s" in sql
    assert "receipt.actor_hash=%s" in sql
    assert "receipt.consumed_at IS NULL" in sql
    assert "receipt.expires_at>CURRENT_TIMESTAMP" in sql
    assert params[2] == "REGULATION_CHECK"
    assert params[3] == "trace-rag-user-request"
    assert params[4] == "c" * 64


def test_answer_rejects_evidence_that_no_longer_joins_to_authorized_rows() -> None:
    request_id = uuid4()
    evidence = [
        {
            "evidence_id": "MANUAL-ONE:1.0:1:chunk-1",
            "text": "Approved manual content",
            "title": "Manual one",
            "manual_id": "MANUAL-ONE",
            "section_title": "Section",
            "citation": "[Manual one v1.0 p.1 Section]",
        }
    ]
    canonical = json.dumps(
        evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    connection = _Connection(
        [
            _Result(
                (
                    [evidence[0]["evidence_id"]],
                    evidence,
                    hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                )
            ),
            _Result(rows=[]),
        ]
    )
    repository = PgVectorRepository(
        "postgresql://test",
        EMBEDDING,
        MANIFEST_SHA256,
        EXPECTED_DOCUMENTS,
        PROCESSING_SHA256,
    )

    with (
        patch("src.rag.pgvector_repository.psycopg.connect", return_value=connection),
        pytest.raises(RuntimeError, match="authorized corpus rows"),
    ):
        repository.load_answer_evidence(
            retrieval_request_id=str(request_id),
            role="STAFF",
            query="approved question",
            answer_intent="REGULATION_CHECK",
            trace_id=str(request_id),
            actor_hash="c" * 64,
            caller_evidence=evidence,
        )

    evidence_sql = connection.statements[1][0]
    assert "%s=ANY(document.role_scope)" in evidence_sql
    assert "document.approval_status='APPROVED'" in evidence_sql
    assert "document.validity_status!='UNRESOLVED'" in evidence_sql
    assert "document.expires_at>=CURRENT_DATE" in evidence_sql
    assert "chunk.source_document_hash=document.content_checksum" in evidence_sql
    assert "evidence.item->>'evidence_id'" in evidence_sql
    assert len(connection.statements) == 2
    assert connection.rolled_back is True


def test_answer_receipt_is_consumed_once_with_compare_and_set() -> None:
    request_id = uuid4()
    evidence = [
        {
            "evidence_id": "MANUAL-ONE:1.0:1:chunk-1",
            "text": "Approved manual content",
            "title": "Manual one",
            "manual_id": "MANUAL-ONE",
            "section_title": "Section",
            "citation": "[Manual one v1.0 p.1 Section]",
        }
    ]
    canonical = json.dumps(
        evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    connection = _Connection(
        [
            _Result(
                (
                    [evidence[0]["evidence_id"]],
                    evidence,
                    hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                )
            ),
            _Result(rows=[(1, "MANUAL-ONE", evidence[0]["evidence_id"])]),
            _Result(rowcount=0),
        ]
    )
    repository = PgVectorRepository(
        "postgresql://test",
        EMBEDDING,
        MANIFEST_SHA256,
        EXPECTED_DOCUMENTS,
        PROCESSING_SHA256,
    )

    with (
        patch("src.rag.pgvector_repository.psycopg.connect", return_value=connection),
        pytest.raises(RuntimeError, match="could not be consumed"),
    ):
        repository.load_answer_evidence(
            retrieval_request_id=str(request_id),
            role="STAFF",
            query="approved question",
            answer_intent="REGULATION_CHECK",
            trace_id=str(request_id),
            actor_hash="c" * 64,
            caller_evidence=evidence,
        )

    consume_sql = connection.statements[2][0]
    assert "SET consumed_at=CURRENT_TIMESTAMP" in consume_sql
    assert "consumed_at IS NULL" in consume_sql
    assert "expires_at>CURRENT_TIMESTAMP" in consume_sql
    assert connection.rolled_back is True


def test_retrieval_receipt_migration_is_closed_and_replayable() -> None:
    migration = (
        Path(__file__).resolve().parents[2]
        / "infrastructure/rag/db/init/011_retrieval_evidence_receipts.sql"
    )
    sql = migration.read_text(encoding="utf-8")

    assert "receipt_id UUID PRIMARY KEY" in sql
    assert "release_id UUID NOT NULL REFERENCES corpus_releases" in sql
    assert "evidence_payload JSONB NOT NULL" in sql
    assert "answer_query_sha256" in sql
    assert "answer_intent TEXT NOT NULL" in sql
    assert "trace_id VARCHAR(128) NOT NULL" in sql
    assert "length(btrim(trace_id)) BETWEEN 1 AND 128" in sql
    assert "actor_hash TEXT NOT NULL" in sql
    assert "INTERVAL '5 minutes'" in sql
    assert "consumed_at TIMESTAMPTZ" in sql
    assert "idx_retrieval_evidence_receipts_expires" in sql
    assert "unbound retrieval receipts require explicit expiry or cleanup" in sql
    assert "DELETE FROM retrieval_evidence_receipts" not in sql
    assert "CREATE TABLE IF NOT EXISTS" in sql
