from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


BACKEND = Path(__file__).resolve().parents[1]
REPOSITORY = BACKEND.parents[1]
CONTRACT_DIRECTORY = BACKEND / "contracts"
FIXTURE_DIRECTORY = REPOSITORY / "tests" / "backend" / "fixtures" / "api" / "v0.1"
OPENAPI_PATH = CONTRACT_DIRECTORY / "openapi.v0.1.json"
STATE_MAPPING_PATH = CONTRACT_DIRECTORY / "state_mapping.v0.1.json"

sys.path.insert(0, str(BACKEND))

from app.contract_examples import STATE_MAPPING, contract_fixtures  # noqa: E402
from app.main import app  # noqa: E402


def serialize(value: Any) -> str:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def expected_files() -> dict[Path, str]:
    files = {
        OPENAPI_PATH: serialize(app.openapi()),
        STATE_MAPPING_PATH: serialize(STATE_MAPPING),
    }
    files.update(
        {
            FIXTURE_DIRECTORY / f"{name}.json": serialize(
                response.model_dump(mode="json")
            )
            for name, response in contract_fixtures().items()
        }
    )
    return files


def export_contracts() -> None:
    for path, content in expected_files().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"UPDATED {path.relative_to(REPOSITORY)}")


def check_contracts() -> None:
    drifted: list[str] = []
    for path, expected in expected_files().items():
        if not path.exists() or path.read_text(encoding="utf-8") != expected:
            drifted.append(str(path.relative_to(REPOSITORY)))
    if drifted:
        raise SystemExit("OPENAPI_CONTRACT_DRIFT\n" + "\n".join(drifted))
    print("OPENAPI_CONTRACT_VERIFIED")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="생성 결과와 저장된 계약 파일이 같은지 확인합니다.",
    )
    arguments = parser.parse_args()
    if arguments.check:
        check_contracts()
    else:
        export_contracts()


if __name__ == "__main__":
    main()
