from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .embedding_provider import OPENAI_EMBEDDING_MODELS


@dataclass(frozen=True)
class VectorSettings:
    project_root: Path
    config_dir: Path
    migrations_dir: Path
    manuals_dir: Path
    smoke_queries_path: Path
    evidence_dir: Path
    backup_dir: Path
    database_url: str
    model_path: Path
    embedding_provider: str
    embedding_endpoint: str
    embedding_api_key: str
    embedding_timeout_seconds: float
    embedding_maximum_attempts: int
    model_id: str
    model_revision: str
    dimension: int
    device: str
    batch_size: int
    query_prompt_name: str
    max_sequence_length: int
    chunk_max_tokens: int
    chunk_overlap_tokens: int
    reranker_path: str | None

    @classmethod
    def load(cls, project_root: Path) -> "VectorSettings":
        root = project_root.resolve()
        database_url = os.getenv("RAG_DATABASE_URL", "").strip()
        if not database_url:
            raise ValueError("RAG_DATABASE_URL is required")
        config_dir = cls._path_from_env("RAG_CONFIG_DIR", root / "config" / "rag", root)
        migrations_dir = cls._path_from_env(
            "RAG_MIGRATIONS_DIR", root / "infrastructure" / "rag" / "db" / "init", root
        )
        manuals_dir = cls._path_from_env("RAG_MANUALS_DIR", root / "data" / "rag" / "manuals", root)
        smoke_queries_path = cls._path_from_env(
            "RAG_SMOKE_QUERIES_PATH", root / "evals" / "testsets" / "rag" / "smoke_queries.json", root
        )
        evidence_dir = cls._path_from_env(
            "RAG_EVIDENCE_DIR", root / "evals" / "runs" / "rag", root
        )
        backup_dir = cls._path_from_env("RAG_BACKUP_DIR", root / "backups" / "rag", root)
        embedding = json.loads((config_dir / "embedding.json").read_text(encoding="utf-8"))
        retrieval = json.loads(
            (config_dir / "vector_retrieval.json").read_text(encoding="utf-8")
        )
        configured_model_path = os.getenv("RAG_MODEL_PATH", embedding["local_path"])
        provider = os.getenv("RAG_EMBEDDING_PROVIDER", embedding.get("provider", "qwen")).strip().lower()
        if provider not in {"openai", "qwen"}:
            raise ValueError(f"Unsupported RAG_EMBEDDING_PROVIDER: {provider}")
        model_id = os.getenv("OPENAI_EMBEDDING_MODEL", embedding["model_id"]).strip() if provider == "openai" else embedding["model_id"]
        dimension = int(os.getenv("OPENAI_EMBEDDING_DIMENSIONS", str(embedding["dimension"]))) if provider == "openai" else int(embedding["dimension"])
        if provider == "openai" and model_id not in OPENAI_EMBEDDING_MODELS:
            raise ValueError(
                "OPENAI_EMBEDDING_MODEL must be text-embedding-3-small or "
                "text-embedding-3-large"
            )
        if dimension != int(embedding["dimension"]):
            raise ValueError(
                "Embedding dimension must match the configured pgvector schema"
            )
        return cls(
            project_root=root,
            config_dir=config_dir,
            migrations_dir=migrations_dir,
            manuals_dir=manuals_dir,
            smoke_queries_path=smoke_queries_path,
            evidence_dir=evidence_dir,
            backup_dir=backup_dir,
            database_url=database_url,
            model_path=cls._resolve_path(configured_model_path, root),
            embedding_provider=provider,
            embedding_endpoint=os.getenv("OPENAI_EMBEDDING_ENDPOINT", "https://api.openai.com/v1/embeddings").strip(),
            embedding_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            embedding_timeout_seconds=float(os.getenv("OPENAI_EMBEDDING_TIMEOUT_SECONDS", "30")),
            embedding_maximum_attempts=int(os.getenv("OPENAI_EMBEDDING_MAX_ATTEMPTS", "3")),
            model_id=model_id,
            model_revision=(f"{model_id}:d{dimension}" if provider == "openai" else embedding["revision"]),
            dimension=dimension,
            device=os.getenv("RAG_DEVICE", embedding["device"]).strip().lower(),
            batch_size=int(embedding["batch_size"]),
            query_prompt_name=embedding["query_prompt_name"],
            max_sequence_length=int(embedding.get("max_sequence_length", 2048)),
            chunk_max_tokens=int(retrieval.get("chunk_max_tokens", 384)),
            chunk_overlap_tokens=int(retrieval.get("chunk_overlap_tokens", 64)),
            reranker_path=os.getenv("RERANKER_PATH", "").strip() or None,
        )

    @staticmethod
    def _path_from_env(name: str, default: Path, root: Path) -> Path:
        return VectorSettings._resolve_path(os.getenv(name, str(default)), root)

    @staticmethod
    def _resolve_path(value: str | Path, root: Path) -> Path:
        path = Path(value)
        return path.resolve() if path.is_absolute() else (root / path).resolve()
