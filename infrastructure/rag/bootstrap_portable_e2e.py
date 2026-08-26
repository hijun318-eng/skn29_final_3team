from __future__ import annotations

import argparse
import os
import subprocess
import sys
import socket
import time
from pathlib import Path


class PortableRagBootstrap:
    """Automate model preparation, Compose startup, ingestion, security checks, and RAG E2E."""

    _PROJECT_NAME = "answervice-rag-e2e"

    def __init__(self, repository_root: Path) -> None:
        self._root = repository_root
        self._models_dir = self._root / "models"
        self._model_dir = self._models_dir / "Qwen3-Embedding-0.6B"
        self._environment = os.environ.copy()
        self._environment.setdefault("RAG_MODELS_DIR", str(self._models_dir))
        self._environment["RAG_API_PORT"] = str(self._free_port())

    def run(self, download_model: bool, keep_running: bool) -> None:
        try:
            self.prepare(download_model)
            self.start_services()
            self.migrate_database()
            self.wait_until_ready()
            self.ingest_documents()
            self.verify_security_contracts()
            self.run_end_to_end()
        finally:
            if not keep_running:
                self.stop_services()

    def prepare(self, download_model: bool) -> None:
        if not self._model_dir.exists():
            if not download_model:
                raise RuntimeError(f"Embedding model is missing: {self._model_dir}. Re-run with --download-model.")
            self._download_embedding_model()
        self._run(sys.executable, "infrastructure/rag/prepare_build_context.py", "--output", "tmp/rag-build-context")

    def start_services(self) -> None:
        self._remove_conflicting_containers()
        self._compose("build", "rag-api")
        self._compose("--profile", "rag", "up", "-d")

    def _remove_conflicting_containers(self) -> None:
        for name in ("answervice-rag-api", "answervice-rag-local-answer", "answervice-rag-pgvector", "answervice-rag-e2e"):
            subprocess.run(("docker", "rm", "-f", name), cwd=self._root, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(("docker", "volume", "rm", "-f", "answervice-rag-e2e_answervice-rag-pgdata"), cwd=self._root, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def wait_until_ready(self) -> None:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            result = self._compose("exec", "-T", "rag-api", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=5)", check=False)
            if result.returncode == 0:
                return
            time.sleep(3)
        raise RuntimeError("rag-api did not become ready within 180 seconds.")

    def migrate_database(self) -> None:
        self._compose("exec", "-T", "rag-api", "python", "-m", "src.rag.vector_cli", "migrate")

    def ingest_documents(self) -> None:
        self._compose("exec", "-T", "rag-api", "python", "-m", "src.rag.vector_cli", "ingest")

    def verify_security_contracts(self) -> None:
        self._compose(
            "exec", "-T",
            "-e", "RAG_E2E_BASE_URL=http://rag-api:8000",
            "-e", "RAG_E2E_GATEWAY_HMAC_SECRET=rag-local-dev-hmac-secret-change-before-shared-use",
            "rag-api", "python", "-m", "src.rag.e2e.security_live_probe",
        )

    def run_end_to_end(self) -> None:
        self._compose("run", "--rm", "rag-e2e")

    def stop_services(self) -> None:
        self._compose("down", "--volumes", "--remove-orphans", check=False)

    @staticmethod
    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            return int(probe.getsockname()[1])

    def _download_embedding_model(self) -> None:
        try:
            from huggingface_hub import snapshot_download
        except ImportError as error:
            raise RuntimeError("huggingface_hub is required for --download-model.") from error
        self._models_dir.mkdir(parents=True, exist_ok=True)
        snapshot_download(repo_id="Qwen/Qwen3-Embedding-0.6B", local_dir=str(self._model_dir), local_dir_use_symlinks=False)

    def _compose(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.setdefault("RAG_MODELS_DIR", str(self._models_dir))
        command = (
            "docker-compose", "-p", self._PROJECT_NAME,
            "-f", "infrastructure/rag/compose.fragment.yml",
            "-f", "infrastructure/rag/compose.api.fragment.yml",
            *arguments,
        )
        return self._run(*command, environment=environment, check=check)

    def _run(self, *arguments: str, environment: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(arguments, cwd=self._root, check=check, env=environment, text=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fully automate portable Manual/Policy RAG E2E")
    parser.add_argument("--download-model", action="store_true", help="Download Qwen3 embedding model if absent")
    parser.add_argument("--keep-running", action="store_true", help="Keep the RAG Docker services running after successful E2E")
    arguments = parser.parse_args()
    PortableRagBootstrap(Path(__file__).resolve().parents[2]).run(arguments.download_model, arguments.keep_running)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
