from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from .vector_settings import VectorSettings


class PgBackupRestoreValidator:
    CONTAINER = "answervice-rag-pgvector"
    SOURCE_DATABASE = "answervice_rag"
    RESTORE_DATABASE = "answervice_rag_restore_check_20260803"
    USER = "rag_local"
    CONTAINER_BACKUP = "/tmp/answervice_rag_20260803.dump"

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root.resolve()
        self._settings = VectorSettings.load(self._project_root)
        if not self.RESTORE_DATABASE.startswith("answervice_rag_restore_check_"):
            raise ValueError("Unsafe restore database name")

    def validate(self) -> dict[str, object]:
        backup_path = self._settings.backup_dir / "answervice_rag_20260803.dump"
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        self._docker("dropdb", "--if-exists", "-U", self.USER, self.RESTORE_DATABASE)
        try:
            self._docker(
                "pg_dump", "-U", self.USER, "-d", self.SOURCE_DATABASE,
                "-Fc", "-f", self.CONTAINER_BACKUP,
            )
            self._run(["docker", "cp", f"{self.CONTAINER}:{self.CONTAINER_BACKUP}", str(backup_path)])
            self._docker("createdb", "-U", self.USER, self.RESTORE_DATABASE)
            self._docker(
                "pg_restore", "-U", self.USER, "-d", self.RESTORE_DATABASE,
                self.CONTAINER_BACKUP,
            )
            original = self._counts(self.SOURCE_DATABASE)
            restored = self._counts(self.RESTORE_DATABASE)
            passed = original == restored and original["documents"] > 0 and original["chunks"] > 0
            report = {
                "status": "SUCCESS" if passed else "FAILED",
                "backup_file": str(backup_path),
                "backup_size_bytes": backup_path.stat().st_size,
                "backup_sha256": hashlib.sha256(backup_path.read_bytes()).hexdigest(),
                "original": original,
                "restored": restored,
                "temporary_database_removed": True,
            }
            evidence = self._settings.evidence_dir / "backup_restore_validation.json"
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return report
        finally:
            self._docker("dropdb", "--if-exists", "-U", self.USER, self.RESTORE_DATABASE)

    def _counts(self, database: str) -> dict[str, int]:
        sql = (
            "SELECT (SELECT COUNT(*) FROM documents),"
            "(SELECT COUNT(*) FROM document_chunks),"
            "(SELECT COUNT(*) FROM ingestion_runs),"
            "(SELECT COUNT(*) FROM retrieval_audit_logs),"
            "(SELECT COUNT(*) FROM document_versions),"
            "(SELECT COUNT(*) FROM document_lifecycle_logs),"
            "(SELECT COUNT(*) FROM api_security_audit_logs),"
            "(SELECT COUNT(*) FROM api_request_nonces);"
        )
        output = self._docker("psql", "-U", self.USER, "-d", database, "-Atc", sql)
        values = [int(value) for value in output.split("|")]
        names = (
            "documents", "chunks", "ingestion_runs", "retrieval_audit_logs",
            "document_versions", "lifecycle_logs", "security_audit_logs", "request_nonces",
        )
        return dict(zip(names, values, strict=True))

    def _docker(self, *arguments: str) -> str:
        return self._run(["docker", "exec", self.CONTAINER, *arguments])

    @staticmethod
    def _run(command: list[str]) -> str:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        return completed.stdout.strip()
