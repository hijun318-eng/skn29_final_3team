"""환경 기반 실런타임 E2E 검증을 시작하고 결과 보고서 경로와 종료 상태를 출력한다."""

from __future__ import annotations

import argparse
import json
import sys

from .contracts import DynamicE2EConfig, E2EConfigurationError, E2EStage
from .orchestrator import DynamicE2EOrchestrator


def build_parser() -> argparse.ArgumentParser:
    """보고서 본문 출력 여부만 허용하는 E2E 명령행 인자 파서를 구성한다."""

    parser = argparse.ArgumentParser(
        description="Run a real HTTP RAG, ML and Analysis Core E2E validation without mocks.",
    )
    parser.add_argument(
        "--print-report",
        action="store_true",
        help="Print the persisted report to standard output after execution.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """환경 설정을 검증해 E2E를 실행하고 성공·실패·설정 차단을 0·1·2로 구분한다."""

    arguments = build_parser().parse_args(argv)
    try:
        config = DynamicE2EConfig.from_environment()
    except E2EConfigurationError as error:
        print(json.dumps({"status": "BLOCKED", "error_code": "E2E_CONFIG_INVALID", "message": str(error)}))
        return 2

    orchestrator = DynamicE2EOrchestrator(config)
    report = orchestrator.run()
    report_path = orchestrator.persist(report)
    payload = report.to_dict()
    payload["report_path"] = str(report_path)
    if arguments.print_report:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"final_stage": report.final_stage.value, "report_path": str(report_path)}))
    return 0 if report.final_stage is E2EStage.SUCCEEDED else 1


if __name__ == "__main__":
    sys.exit(main())
