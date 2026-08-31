"""SQLite 기반 로컬 RAG ingest·status·search 검증 명령을 제공한다."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .application import LocalRagApplication


def build_parser() -> argparse.ArgumentParser:
    """로컬 project root와 ingest·status·search 인자를 정의한 parser를 반환한다."""

    parser = argparse.ArgumentParser(description="Answervice 로컬 RAG 검증 CLI")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="로컬 RAG 프로젝트 루트")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("ingest", help="allowlist 문서를 적재합니다")
    subcommands.add_parser("status", help="현재 검증 상태를 표시합니다")
    search = subcommands.add_parser("search", help="문서를 검색합니다")
    search.add_argument("query")
    search.add_argument("--role", default="STAFF")
    search.add_argument("--top-k", type=int, default=3)
    search.add_argument("--allow-unresolved-validity", action="store_true")
    return parser


def main() -> int:
    """선택 명령을 실행해 JSON을 출력하고 성공 종료 코드를 반환한다."""

    arguments = build_parser().parse_args()
    application = LocalRagApplication(arguments.root)
    if arguments.command == "ingest":
        payload = application.ingest()
    elif arguments.command == "status":
        payload = application.status()
    else:
        results = application.search(
            arguments.query,
            arguments.role,
            arguments.top_k,
            arguments.allow_unresolved_validity,
        )
        payload = {"no_evidence": not results, "results": [asdict(result) for result in results]}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
