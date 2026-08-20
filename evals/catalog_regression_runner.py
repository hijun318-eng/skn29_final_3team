"""SQL 근거에 결속된 Semantic 후보의 범용 구조 회귀 행렬을 생성·검사한다."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "app" / "backend"
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
for entry in (str(ROOT), str(BACKEND), str(DATAHUB)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.services.analysis.logical_plan import (  # noqa: E402
    active_analysis_capabilities,
)
from evals.catalog_regression import (  # noqa: E402
    CatalogRegressionError,
    build_catalog_regression,
    evaluate_catalog_observations,
)
from runtime_governance_draft import build_draft  # noqa: E402
from src.data.analysis_capability_contract import (  # noqa: E402
    AnalysisCapabilityError,
    compile_analysis_capability_contract,
)


def main() -> int:
    """명시된 후보·SQL만 읽어 release-bound 구조 Gate 또는 반복 관측 점수를 출력한다."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--semantic-candidate", type=Path, required=True)
    parser.add_argument("--sql-directory", type=Path, required=True)
    parser.add_argument("--runtime-evidence", type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--observations", type=Path)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--include-cases", action="store_true")
    arguments = parser.parse_args()
    try:
        candidate = _load_json(
            arguments.semantic_candidate,
            5_000_000,
            "semantic candidate",
        )
        if not isinstance(candidate, dict):
            raise CatalogRegressionError("semantic candidate must be an object")
        draft = build_draft(
            arguments.sql_directory,
            str(candidate.get("serving_schema") or ""),
            str(candidate.get("release_id") or ""),
        )
        if candidate.get("source_sql_sha256") != draft.source_sha256:
            raise CatalogRegressionError(
                "semantic candidate source SQL checksum does not match"
            )
        fields_by_asset = {
            view.fqn: frozenset(field.name for field in view.fields)
            for view in draft.views
        }
        family_columns = {
            str(item["id"]): frozenset(map(str, item["columns"]))
            for item in _mapping_list(
                candidate.get("dimension_families"),
                "dimension families",
            )
        }
        capability = compile_analysis_capability_contract(
            candidate.get("planning_contract"),
            available_fields_by_asset=fields_by_asset,
            dimension_family_columns=family_columns,
        )
        runtime_evidence = (
            _load_json(arguments.runtime_evidence, 1_000_000, "runtime evidence")
            if arguments.runtime_evidence is not None
            else None
        )
        result = build_catalog_regression(
            candidate,
            capability,
            active_analysis_capabilities(),
            runtime_evidence_value=runtime_evidence,
        )
        if arguments.observations is not None:
            result = evaluate_catalog_observations(
                result,
                _load_jsonl(
                    arguments.observations,
                    20_000_000,
                    "catalog observations",
                ),
                repeat=arguments.repeat,
            )
        elif not arguments.include_cases:
            result = {key: value for key, value in result.items() if key != "cases"}
    except (
        AnalysisCapabilityError,
        CatalogRegressionError,
        KeyError,
        OSError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        print(
            json.dumps(
                {"status": "INVALID", "error": str(error)},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


def _read(path: Path, limit: int, context: str) -> bytes:
    """일반 파일 하나만 bounded 크기로 읽는다."""

    target = path.resolve()
    if not target.is_file() or target.stat().st_size > limit:
        raise CatalogRegressionError(f"{context} is unavailable or too large")
    return target.read_bytes()


def _load_json(path: Path, limit: int, context: str) -> Any:
    """bounded UTF-8 JSON 문서를 읽는다."""

    return json.loads(_read(path, limit, context).decode("utf-8"))


def _load_jsonl(path: Path, limit: int, context: str) -> list[object]:
    """빈 줄이 없는 bounded UTF-8 JSONL을 읽는다."""

    lines = _read(path, limit, context).decode("utf-8").splitlines()
    if not lines or any(not line.strip() for line in lines):
        raise CatalogRegressionError(
            f"{context} must be non-empty JSONL without blank lines"
        )
    return [json.loads(line) for line in lines]


def _mapping_list(value: object, context: str) -> tuple[dict[str, Any], ...]:
    """후보 하위 배열을 object 목록으로 제한한다."""

    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise CatalogRegressionError(f"{context} must be an object array")
    return tuple(value)


if __name__ == "__main__":
    raise SystemExit(main())
