from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


class BootstrapError(RuntimeError):
    pass


class EnvFile:
    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for raw_line in self.path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
        return values

    def set(self, key: str, value: str) -> None:
        text = self.path.read_text(encoding="utf-8-sig")
        newline = "\r\n" if "\r\n" in text else "\n"
        lines = text.splitlines()
        replacement = f"{key}={value}"
        for index, line in enumerate(lines):
            if line.strip().startswith(f"{key}="):
                lines[index] = replacement
                break
        else:
            lines.append(replacement)
        self.path.write_text(newline.join(lines) + newline, encoding="utf-8")


class PortableRagBootstrap:
    DOCKER_CONTEXT = "desktop-linux"
    PROJECT_NAME = "answervice"
    STATE_QUERY = """
        SELECT json_build_object(
            'document_count', (SELECT COUNT(*) FROM documents WHERE deleted_at IS NULL),
            'approved_document_count', (SELECT COUNT(*) FROM documents
                WHERE deleted_at IS NULL AND approval_status = 'APPROVED'),
            'validated_document_count', (SELECT COUNT(*) FROM documents
                WHERE deleted_at IS NULL AND validity_status != 'UNRESOLVED'),
            'chunk_count', (SELECT COUNT(*) FROM document_chunks WHERE deleted_at IS NULL),
            'vector_count', (SELECT COUNT(*) FROM document_chunks
                WHERE deleted_at IS NULL AND embedding IS NOT NULL),
            'provider_count', (SELECT COUNT(DISTINCT embedding_provider)
                FROM document_chunks WHERE deleted_at IS NULL),
            'provider', (SELECT MIN(embedding_provider)
                FROM document_chunks WHERE deleted_at IS NULL),
            'model_count', (SELECT COUNT(DISTINCT embedding_model)
                FROM document_chunks WHERE deleted_at IS NULL),
            'model', (SELECT MIN(embedding_model)
                FROM document_chunks WHERE deleted_at IS NULL),
            'dimension_count', (SELECT COUNT(DISTINCT embedding_dimensions)
                FROM document_chunks WHERE deleted_at IS NULL),
            'dimensions', (SELECT MIN(embedding_dimensions)
                FROM document_chunks WHERE deleted_at IS NULL)
        )::text
    """

    def __init__(
        self,
        root: Path,
        force_reindex: bool,
        verify: bool,
        approve_local_manuals: bool,
    ) -> None:
        self.root = root
        self.env_file = EnvFile(root / ".env")
        self.force_reindex = force_reindex
        self.verify = verify
        self.approve_local_manuals = approve_local_manuals
        self.environment = os.environ.copy()
        self.lock_fd: int | None = None
        self.lock_path = root / "tmp" / "rag-bootstrap.lock"
        self.manual_dir = root / "data" / "rag" / "manuals"
        self.pdf_count = 0
        self.expected_provider = "openai"
        self.expected_model = "text-embedding-3-small"
        self.expected_dimensions = 1024

    def run(self) -> None:
        try:
            self._acquire_lock()
            self._prepare_environment()
            self._start_services()
            self._migrate_database()
            self._wait_for_ready()
            state = self._read_state()
            if self.force_reindex or not self._is_current(state):
                self._print_state("Reindex required", state)
                self._ingest_documents()
                state = self._read_state()
            if (
                self.approve_local_manuals
                and (
                    int(state.get("approved_document_count") or 0) != self.pdf_count
                    or int(state.get("validated_document_count") or 0) != self.pdf_count
                )
            ):
                self._approve_local_manuals()
                state = self._read_state()
            if not self._is_current(state):
                self._print_state("Invalid state after ingestion", state)
                raise BootstrapError(
                    "RAG data is incomplete or stale after ingestion. "
                    "Review the ingestion logs before retrying."
                )
            self._print_state("RAG data ready", state)
            if self.verify:
                self._run_end_to_end()
            self._print_backend_guidance()
        finally:
            self._release_lock()

    def _prepare_environment(self) -> None:
        if not self.env_file.path.exists():
            raise BootstrapError("Missing .env file in the repository root.")
        self.env_file.set("RAG_FEATURE_ENABLED", "1")
        values = self.env_file.read()
        self._require_secret(values, "OPENAI_API_KEY")
        self._require_secret(values, "RAG_DB_PASSWORD")
        self._require_secret(values, "RAG_GATEWAY_HMAC_SECRET", minimum_length=32)

        self.expected_provider = values.get("RAG_EMBEDDING_PROVIDER", "openai").lower()
        if self.expected_provider != "openai":
            raise BootstrapError(
                "This bootstrap supports the current OpenAI embedding runtime only."
            )
        self.expected_model = values.get(
            "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"
        )
        self.expected_dimensions = int(values.get("OPENAI_EMBEDDING_DIMENSIONS", "1024"))

        configured_manual_dir = values.get("RAG_MANUALS_HOST_DIR", "").strip()
        if configured_manual_dir:
            candidate = Path(configured_manual_dir)
            self.manual_dir = candidate if candidate.is_absolute() else self.root / candidate
        self.pdf_count = len(list(self.manual_dir.glob("*.pdf")))
        if self.pdf_count == 0:
            raise BootstrapError(f"No PDF manuals found in {self.manual_dir}")

        self.environment.update(
            {
                "COMPOSE_PROJECT_NAME": self.PROJECT_NAME,
                "RAG_FEATURE_ENABLED": "1",
                "RAG_MANUALS_HOST_DIR": str(self.manual_dir.resolve()),
                "RAG_E2E_GATEWAY_HMAC_SECRET": values["RAG_GATEWAY_HMAC_SECRET"],
            }
        )
        context = self._run("docker", "context", "show", capture=True).stdout.strip()
        if context != self.DOCKER_CONTEXT:
            self._run("docker", "context", "use", self.DOCKER_CONTEXT)

    @staticmethod
    def _require_secret(
        values: dict[str, str], key: str, minimum_length: int = 1
    ) -> None:
        value = values.get(key, "").strip()
        invalid_markers = ("change_me", "replace_me", "your_", "example")
        if len(value) < minimum_length or any(marker in value.lower() for marker in invalid_markers):
            raise BootstrapError(f"Set a valid {key} value in .env before starting RAG.")

    def _compose(self, *args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
        return self._run(
            "docker", "--context", self.DOCKER_CONTEXT,
            "compose", "--project-name", self.PROJECT_NAME,
            "--env-file", str(self.env_file.path),
            "-f", str(self.root / "compose.yml"), "--profile", "rag",
            *args, capture=capture,
        )

    def _start_services(self) -> None:
        print("Starting persistent RAG services...")
        self._compose(
            "up", "-d", "--build", "rag-postgres", "rag-local-answer", "rag-api"
        )

    def _migrate_database(self) -> None:
        self._compose(
            "exec", "-T", "rag-api", "python", "-m", "src.rag.vector_cli", "migrate"
        )

    def _wait_for_ready(self, timeout_seconds: int = 180) -> None:
        deadline = time.monotonic() + timeout_seconds
        probe = (
            "import urllib.request; "
            "urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3).read()"
        )
        while time.monotonic() < deadline:
            result = self._compose(
                "exec", "-T", "rag-api", "python", "-c", probe, capture=True
            )
            if result.returncode == 0:
                return
            time.sleep(3)
        raise BootstrapError("RAG API did not become ready within 180 seconds.")

    def _read_state(self) -> dict[str, object]:
        code = (
            "import os,psycopg; "
            f"sql={self.STATE_QUERY!r}; "
            "conn=psycopg.connect(os.environ['RAG_DATABASE_URL']); "
            "print(conn.execute(sql).fetchone()[0])"
        )
        result = self._compose(
            "exec", "-T", "rag-api", "python", "-c", code, capture=True
        )
        if result.returncode != 0:
            raise BootstrapError(result.stderr.strip() or "Unable to inspect RAG database state.")
        return json.loads(result.stdout.strip())

    def _is_current(self, state: dict[str, object]) -> bool:
        chunk_count = int(state.get("chunk_count") or 0)
        return all(
            (
                int(state.get("document_count") or 0) == self.pdf_count,
                int(state.get("approved_document_count") or 0) == self.pdf_count,
                int(state.get("validated_document_count") or 0) == self.pdf_count,
                chunk_count > 0,
                int(state.get("vector_count") or 0) == chunk_count,
                int(state.get("provider_count") or 0) == 1,
                state.get("provider") == self.expected_provider,
                int(state.get("model_count") or 0) == 1,
                state.get("model") == self.expected_model,
                int(state.get("dimension_count") or 0) == 1,
                int(state.get("dimensions") or 0) == self.expected_dimensions,
            )
        )

    def _ingest_documents(self) -> None:
        print(f"Ingesting {self.pdf_count} PDF manuals with {self.expected_model}...")
        self._compose(
            "exec", "-T", "rag-api", "python", "-m", "src.rag.vector_cli", "ingest"
        )

    def _approve_local_manuals(self) -> None:
        print("Approving local bootstrap manuals with an auditable lifecycle record...")
        sql = """
            WITH approved AS (
                UPDATE documents
                SET approval_status = 'APPROVED',
                    validity_status = 'VALIDATED',
                    updated_at = CURRENT_TIMESTAMP
                WHERE deleted_at IS NULL
                  AND (
                      approval_status != 'APPROVED'
                      OR validity_status = 'UNRESOLVED'
                  )
                RETURNING manual_id
            )
            INSERT INTO document_lifecycle_logs(manual_id, action, actor_role, reason)
            SELECT manual_id, 'UPSERT', 'SYSTEM_ADMIN', 'LOCAL_BOOTSTRAP_APPROVAL'
            FROM approved
        """
        code = (
            "import os,psycopg; "
            f"sql={sql!r}; "
            "conn=psycopg.connect(os.environ['RAG_DATABASE_URL']); "
            "conn.execute(sql); conn.commit()"
        )
        self._compose("exec", "-T", "rag-api", "python", "-c", code)

    def _run_end_to_end(self) -> None:
        print("Running optional live RAG E2E verification...")
        artifact_dir = self.root / "evals" / "runs" / "rag"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        self._compose(
            "run",
            "--rm",
            "-v",
            f"{artifact_dir.resolve()}:/workspace/evals/runs/rag",
            "rag-e2e",
        )

    def _print_backend_guidance(self) -> None:
        result = self._run(
            "docker", "--context", self.DOCKER_CONTEXT, "ps",
            "--filter", f"label=com.docker.compose.project={self.PROJECT_NAME}",
            "--filter", "label=com.docker.compose.service=backend",
            "--format", "{{.ID}}", capture=True,
        )
        if result.stdout.strip():
            print("Backend is running. Recreate it to load RAG_FEATURE_ENABLED=1.")
        else:
            print("RAG is ready. Start the main application normally to load the enabled RAG flag.")

    @staticmethod
    def _print_state(title: str, state: dict[str, object]) -> None:
        print(
            f"{title}: documents={state.get('document_count')}, "
            f"approved={state.get('approved_document_count')}, "
            f"validated={state.get('validated_document_count')}, "
            f"chunks={state.get('chunk_count')}, vectors={state.get('vector_count')}, "
            f"provider={state.get('provider')}, model={state.get('model')}, "
            f"dimensions={state.get('dimensions')}"
        )

    def _acquire_lock(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        if self.lock_path.exists() and time.time() - self.lock_path.stat().st_mtime > 3600:
            self.lock_path.unlink()
        try:
            self.lock_fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self.lock_fd, str(os.getpid()).encode("ascii"))
        except FileExistsError as exc:
            raise BootstrapError("Another RAG bootstrap process is already running.") from exc

    def _release_lock(self) -> None:
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None
        if self.lock_path.exists():
            self.lock_path.unlink()

    def _run(
        self, *command: str, capture: bool = False
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            list(command), cwd=self.root, env=self.environment,
            text=True, capture_output=capture, check=False,
        )
        if result.returncode != 0 and not capture:
            raise BootstrapError(f"Command failed ({result.returncode}): {' '.join(command)}")
        return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start and initialize persistent RAG services.")
    parser.add_argument("--force-reindex", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--approve-local-manuals", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[2]
    try:
        PortableRagBootstrap(
            root,
            args.force_reindex,
            args.verify,
            args.approve_local_manuals,
        ).run()
        return 0
    except (BootstrapError, ValueError) as exc:
        print(f"RAG bootstrap failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
