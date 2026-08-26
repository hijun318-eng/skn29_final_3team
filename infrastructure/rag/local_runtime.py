from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


class LocalRagRuntime:
    """Start the locally built RAG API against an existing pgvector network."""

    def __init__(self, root: Path) -> None:
        self._root = root

    @staticmethod
    def _required(name: str) -> str:
        value = os.getenv(name, "").strip()
        if not value:
            raise RuntimeError(f"{name} must be set before starting rag-api.")
        return value

    @staticmethod
    def _run(*arguments: str) -> str:
        result = subprocess.run(arguments, check=True, text=True, capture_output=True, timeout=90)
        return result.stdout.strip()

    def start(self) -> None:
        database_url = self._required("RAG_DATABASE_URL")
        gateway_secret = self._required("RAG_GATEWAY_HMAC_SECRET")
        answer_endpoint = self._required("RAG_ANSWER_ENDPOINT")
        answer_model = self._required("RAG_ANSWER_MODEL")
        answer_api_key = self._required("RAG_ANSWER_API_KEY")
        network = os.getenv("RAG_NETWORK_NAME", "answervice__rag__v01_default")
        port = os.getenv("RAG_API_PORT", "18082")
        subprocess.run(("docker", "rm", "-f", "answervice-rag-api"), capture_output=True, text=True, timeout=30)
        command = ["docker", "run", "-d", "--name", "answervice-rag-api", "--network", network, "-p", f"127.0.0.1:{port}:8000", "--mount", f"type=bind,source={self._root / 'models'},target=/models,readonly"]
        variables = {"RAG_DATABASE_URL": database_url, "RAG_CONFIG_DIR": "/workspace/config/rag", "RAG_MANUALS_DIR": "/workspace/data/rag/manuals", "RAG_EVIDENCE_DIR": "/workspace/evals/runs/rag", "RAG_BACKUP_DIR": "/backups/rag", "RAG_MODEL_PATH": "/models/Qwen3-Embedding-0.6B", "RAG_GATEWAY_HMAC_SECRET": gateway_secret, "RAG_ANSWER_ENDPOINT": answer_endpoint, "RAG_ANSWER_MODEL": answer_model, "RAG_ANSWER_API_KEY": answer_api_key}
        for key, value in variables.items():
            command.extend(("-e", f"{key}={value}"))
        container_id = self._run(*command, "answervice-rag-api:latest")
        print(json.dumps({"container_id": container_id, "port": int(port), "network": network}))


if __name__ == "__main__":
    LocalRagRuntime(Path(__file__).resolve().parents[2]).start()
