from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .vector_application import VectorRagApplication
from .backup_validation import PgBackupRestoreValidator
from .question_report import EvaluationQuestionReportWriter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenAI Text Embedding + pgvector 내부업무매뉴얼 RAG CLI")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate")
    ingest = commands.add_parser("ingest")
    ingest.add_argument("--limit", type=int)
    commands.add_parser("status")
    commands.add_parser("evaluate-smoke")
    commands.add_parser("evaluate-quality")
    commands.add_parser("validate-lifecycle")
    commands.add_parser("validate-backup-restore")
    commands.add_parser("write-question-report")
    commands.add_parser("write-evidence")
    search = commands.add_parser("search")
    search.add_argument("query")
    search.add_argument("--role", default="STAFF")
    search.add_argument("--top-k", type=int, default=5)
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    if arguments.command == "validate-backup-restore":
        payload = PgBackupRestoreValidator(arguments.root).validate()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if arguments.command == "write-question-report":
        payload = EvaluationQuestionReportWriter(arguments.root).write()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    application = VectorRagApplication(arguments.root)
    actions = {
        "migrate": application.migrate,
        "status": application.status,
        "evaluate-smoke": application.evaluate_smoke,
        "evaluate-quality": application.evaluate_quality,
        "validate-lifecycle": application.validate_lifecycle,
        "write-evidence": application.write_runtime_evidence,
    }
    if arguments.command == "ingest":
        payload = application.ingest(arguments.limit)
    elif arguments.command == "search":
        payload = application.search(
            arguments.query,
            arguments.role,
            arguments.top_k,
            actor_hash=hashlib.sha256(b"RAG_LOCAL_CLI").hexdigest(),
        )
    else:
        payload = actions[arguments.command]()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
