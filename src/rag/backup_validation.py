from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse
from uuid import uuid4

from .corpus_manifest import CorpusManifest
from .processing_profile import processing_profile_sha256
from .vector_settings import VectorSettings


class PgBackupRestoreValidator:
    _DATABASE_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}")
    _CONTAINER_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root.resolve()
        self._settings = VectorSettings.load(self._project_root)
        self._source_database = self._database_identifier("RAG_DB_NAME")
        self._database_user = self._database_identifier("RAG_DB_USER")
        url_database, url_user = self._database_identity(
            self._settings.database_url
        )
        if (
            url_database != self._source_database
            or url_user != self._database_user
        ):
            raise ValueError(
                "RAG_DATABASE_URL database and user must match RAG_DB_NAME and RAG_DB_USER"
            )
        manifest = CorpusManifest.load(
            self._settings.corpus_manifest_path,
            self._settings.manuals_dir,
        )
        self._expected_embedding = {
            "embedding_provider": self._settings.embedding_provider,
            "embedding_model": self._settings.model_id,
            "embedding_dimensions": self._settings.dimension,
            "embedding_version": self._settings.model_revision,
        }
        self._expected_manifest_sha256 = manifest.manifest_sha256
        self._expected_documents = manifest.included_document_checksums
        self._expected_processing_profile_sha256 = processing_profile_sha256(
            self._settings.chunk_max_tokens,
            self._settings.chunk_overlap_tokens,
        )
        self._container = os.getenv(
            "RAG_DB_CONTAINER", "answervice-rag-pgvector"
        ).strip()
        if self._CONTAINER_IDENTIFIER.fullmatch(self._container) is None:
            raise ValueError("RAG_DB_CONTAINER is invalid")
        container_directory = PurePosixPath(
            os.getenv("RAG_BACKUP_CONTAINER_DIR", "/tmp").strip()
        )
        if (
            not container_directory.is_absolute()
            or ".." in container_directory.parts
            or len(str(container_directory)) > 160
        ):
            raise ValueError("RAG_BACKUP_CONTAINER_DIR is invalid")
        self._run_token = uuid4().hex
        source_prefix = self._source_database[:36]
        self._restore_database = (
            f"{source_prefix}_restore_check_{self._run_token[:12]}"
        )
        self._assert_safe_restore_target(
            self._source_database,
            self._restore_database,
        )
        self._backup_filename = f"rag_corpus_{self._run_token}.dump"
        self._container_backup = str(
            container_directory / self._backup_filename
        )
        self._container_restore_input = str(
            container_directory / f"rag_corpus_restore_{self._run_token}.dump"
        )

    def validate(self) -> dict[str, object]:
        backup_path = self._settings.backup_dir / self._backup_filename
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        original: dict[str, object] | None = None
        restored: dict[str, object] | None = None
        operation_error: Exception | None = None
        validation_passed = False
        try:
            self._docker(
                "dropdb", "--if-exists", "-U", self._database_user,
                self._restore_database,
            )
            self._docker(
                "pg_dump", "-U", self._database_user, "-d", self._source_database,
                "-Fc", "-f", self._container_backup,
            )
            self._run(
                [
                    "docker", "cp",
                    f"{self._container}:{self._container_backup}",
                    str(backup_path),
                ]
            )
            if not backup_path.is_file() or backup_path.stat().st_size <= 0:
                raise RuntimeError("RAG host backup artifact is empty or missing")
            self._run(
                [
                    "docker", "cp", str(backup_path),
                    f"{self._container}:{self._container_restore_input}",
                ]
            )
            self._docker(
                "createdb", "-U", self._database_user, self._restore_database
            )
            self._docker(
                "pg_restore", "-U", self._database_user,
                "-d", self._restore_database, self._container_restore_input,
            )
            original = self._active_release_receipt(self._source_database)
            restored = self._active_release_receipt(self._restore_database)
            validation_passed = (
                original == restored
                and self._valid_active_release(original)
                and self._valid_active_release(restored)
            )
        except Exception as error:
            operation_error = error
        finally:
            cleanup = self._cleanup_temporary_resources()

        cleanup_passed = all(cleanup.values())
        backup_exists = backup_path.is_file()
        backup_size = backup_path.stat().st_size if backup_exists else 0
        report = {
            "status": (
                "SUCCESS"
                if operation_error is None and validation_passed and cleanup_passed
                else "FAILED"
            ),
            "source_database": self._source_database,
            "restore_database": self._restore_database,
            "backup_file": str(backup_path),
            "backup_size_bytes": backup_size,
            "backup_sha256": (
                self._file_sha256(backup_path)
                if backup_exists and backup_size > 0
                else None
            ),
            "original": original,
            "restored": restored,
            "cleanup": cleanup,
            "temporary_database_removed": cleanup["restore_database_removed"],
            "error_type": type(operation_error).__name__ if operation_error else None,
        }
        evidence = self._settings.evidence_dir / "backup_restore_validation.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if operation_error is not None:
            raise operation_error
        return report

    def _active_release_receipt(self, database: str) -> dict[str, object]:
        sql = (
            "SELECT release.release_id,release.status,release.embedding_provider,"
            "release.embedding_model,release.embedding_dimensions,release.embedding_version,"
            "release.corpus_manifest_sha256,release.processing_profile_sha256,"
            "release.document_count,"
            "(SELECT COUNT(*) FROM corpus_release_documents d WHERE d.release_id=release.release_id),"
            "(SELECT COUNT(*) FROM corpus_release_documents d WHERE d.release_id=release.release_id AND d.deleted_at IS NOT NULL),"
            "release.chunk_count,"
            "(SELECT COUNT(*) FROM corpus_release_chunks c WHERE c.release_id=release.release_id),"
            "(SELECT COUNT(*) FROM corpus_release_chunks c WHERE c.release_id=release.release_id AND c.deleted_at IS NOT NULL),"
            "(SELECT COUNT(*) FROM corpus_release_chunks c WHERE c.release_id=release.release_id "
            "AND (c.embedding_provider<>release.embedding_provider OR c.embedding_model<>release.embedding_model "
            "OR c.embedding_dimensions<>release.embedding_dimensions OR c.embedding_version<>release.embedding_version "
            "OR c.source_document_hash<>(SELECT d.content_checksum FROM corpus_release_documents d "
            "WHERE d.release_id=c.release_id AND d.manual_id=c.manual_id))),"
            "(SELECT COUNT(*) FROM corpus_release_documents d WHERE d.release_id=release.release_id "
            "AND NOT EXISTS (SELECT 1 FROM corpus_release_chunks c WHERE c.release_id=d.release_id "
            "AND c.manual_id=d.manual_id AND c.deleted_at IS NULL)),"
            "(SELECT COUNT(*) FROM ingestion_runs run WHERE run.run_id=release.release_id AND run.status='SUCCESS'),"
            "(SELECT COALESCE(jsonb_object_agg(d.manual_id,d.content_checksum),'{}'::jsonb)::text "
            "FROM corpus_release_documents d WHERE d.release_id=release.release_id),"
            "(SELECT COUNT(*) FROM corpus_release_documents d WHERE d.release_id=release.release_id "
            "AND d.deleted_at IS NULL AND d.document_status='WORKING_KNOWLEDGE' "
            "AND d.approval_status='APPROVED' AND d.validity_status!='UNRESOLVED' "
            "AND 'STAFF'=ANY(d.role_scope) "
            "AND (d.effective_from IS NULL OR d.effective_from<=CURRENT_DATE) "
            "AND (d.expires_at IS NULL OR d.expires_at>=CURRENT_DATE)) "
            "FROM corpus_active_release active JOIN corpus_releases release ON release.release_id=active.release_id "
            "WHERE active.singleton=TRUE;"
        )
        output = self._docker(
            "psql", "-U", self._database_user, "-d", database, "-Atc", sql
        )
        values = output.split("|")
        names = (
            "release_id", "status", "embedding_provider", "embedding_model",
            "embedding_dimensions", "embedding_version", "corpus_manifest_sha256",
            "processing_profile_sha256", "stored_documents", "documents",
            "deleted_documents", "stored_chunks",
            "chunks", "deleted_chunks", "embedding_metadata_mismatches",
            "documents_without_chunks", "successful_ingestion_runs",
            "document_checksums", "approved_document_count",
        )
        if len(values) != len(names):
            raise RuntimeError("Backup does not contain exactly one active RAG release")
        receipt: dict[str, object] = dict(zip(names, values, strict=True))
        for name in (
            "embedding_dimensions", "stored_documents", "documents",
            "deleted_documents", "stored_chunks", "chunks", "deleted_chunks",
            "embedding_metadata_mismatches", "documents_without_chunks",
            "successful_ingestion_runs", "approved_document_count",
        ):
            receipt[name] = int(str(receipt[name]))
        try:
            document_checksums = json.loads(str(receipt["document_checksums"]))
        except json.JSONDecodeError as error:
            raise RuntimeError("Backup active release document receipt is invalid") from error
        if not isinstance(document_checksums, dict):
            raise RuntimeError("Backup active release document receipt is invalid")
        receipt["document_checksums"] = document_checksums
        return receipt

    def _valid_active_release(self, receipt: dict[str, object]) -> bool:
        return bool(
            receipt.get("status") == "ACTIVE"
            and isinstance(receipt.get("release_id"), str)
            and receipt["release_id"]
            and isinstance(receipt.get("corpus_manifest_sha256"), str)
            and re.fullmatch(
                r"[0-9a-f]{64}", str(receipt["corpus_manifest_sha256"])
            )
            and isinstance(receipt.get("processing_profile_sha256"), str)
            and re.fullmatch(
                r"[0-9a-f]{64}", str(receipt["processing_profile_sha256"])
            )
            and all(
                receipt.get(name) == value
                for name, value in self._expected_embedding.items()
            )
            and receipt.get("corpus_manifest_sha256")
            == self._expected_manifest_sha256
            and receipt.get("processing_profile_sha256")
            == self._expected_processing_profile_sha256
            and receipt.get("document_checksums") == self._expected_documents
            and int(receipt["embedding_dimensions"]) > 0
            and int(receipt["stored_documents"]) > 0
            and receipt["stored_documents"] == receipt["documents"]
            and int(receipt["stored_chunks"]) > 0
            and receipt["stored_chunks"] == receipt["chunks"]
            and receipt["deleted_documents"] == 0
            and receipt["deleted_chunks"] == 0
            and receipt["embedding_metadata_mismatches"] == 0
            and receipt["documents_without_chunks"] == 0
            and receipt["successful_ingestion_runs"] == 1
            and receipt["approved_document_count"] == receipt["stored_documents"]
        )

    def _cleanup_temporary_resources(self) -> dict[str, bool]:
        cleanup_commands = (
            (
                "restore_database_removed",
                (
                    "dropdb", "--if-exists", "-U", self._database_user,
                    self._restore_database,
                ),
            ),
            (
                "container_dump_removed",
                ("rm", "-f", "--", self._container_backup),
            ),
            (
                "container_restore_input_removed",
                ("rm", "-f", "--", self._container_restore_input),
            ),
        )
        results: dict[str, bool] = {}
        for name, command in cleanup_commands:
            try:
                self._docker(*command)
            except Exception:
                results[name] = False
            else:
                results[name] = True
        return results

    def _docker(self, *arguments: str) -> str:
        return self._run(["docker", "exec", self._container, *arguments])

    @classmethod
    def _database_identifier(cls, variable: str) -> str:
        value = os.getenv(variable, "").strip()
        if cls._DATABASE_IDENTIFIER.fullmatch(value) is None:
            raise ValueError(f"{variable} is required and must be a safe identifier")
        return value

    @classmethod
    def _database_identity(cls, database_url: str) -> tuple[str, str]:
        parsed = urlparse(database_url)
        database = unquote(parsed.path.lstrip("/"))
        user = unquote(parsed.username or "")
        if (
            parsed.scheme not in {"postgres", "postgresql"}
            or "/" in database
            or cls._DATABASE_IDENTIFIER.fullmatch(database) is None
            or cls._DATABASE_IDENTIFIER.fullmatch(user) is None
        ):
            raise ValueError("RAG_DATABASE_URL database identity is invalid")
        return database, user

    @classmethod
    def _assert_safe_restore_target(cls, source: str, restore: str) -> None:
        if (
            cls._DATABASE_IDENTIFIER.fullmatch(restore) is None
            or restore == source
            or not restore.startswith(f"{source[:36]}_restore_check_")
        ):
            raise ValueError("Unsafe restore database name")

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _run(command: list[str]) -> str:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        return completed.stdout.strip()
