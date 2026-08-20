"""Manifest에 고정된 Trino SQL에서 일반화된 serving 복구 계획을 추출한다."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from sqlglot import exp, parse
from sqlglot.errors import ErrorLevel


def _namespace_parts(schema: str) -> tuple[str, str]:
    parts = tuple(schema.split("."))
    if len(parts) != 2 or any(not part for part in parts):
        raise ValueError("serving schema must use catalog.schema form")
    return parts[0], parts[1]


def _target_parts(target: exp.Expression) -> tuple[str, ...]:
    """인용 여부와 무관하게 SQLGlot identifier 값을 순서대로 반환한다."""

    if isinstance(target, exp.Table):
        return tuple(
            part
            for part in (str(target.catalog), str(target.db), str(target.name))
            if part
        )
    if isinstance(target, exp.Column):
        return tuple(
            part
            for part in (
                str(target.catalog),
                str(target.db),
                str(target.table),
                str(target.name),
            )
            if part
        )
    raise ValueError(f"unsupported serving target: {type(target).__name__}")


def _view_identity(statement: exp.Create, schema: str) -> str:
    catalog, database = _namespace_parts(schema)
    parts = _target_parts(statement.this)
    if len(parts) != 3 or parts[:2] != (catalog, database):
        raise ValueError(f"view target escaped release schema: {'.'.join(parts)}")
    return ".".join(parts)


def inspect(paths: tuple[Path, ...], schema: str) -> tuple[str, ...]:
    """요청 schema에 속한 중복 없는 View FQN을 정렬해 반환한다."""

    views: set[str] = set()
    for path in paths:
        statements = parse(
            path.read_text(encoding="utf-8-sig"),
            read="trino",
            error_level=ErrorLevel.RAISE,
        )
        for statement in statements:
            if not isinstance(statement, exp.Create):
                continue
            if str(statement.args.get("kind", "")).upper() != "VIEW":
                continue
            target = _view_identity(statement, schema)
            if target in views:
                raise ValueError(f"view target is declared more than once: {target}")
            views.add(target)
    if not views:
        raise ValueError("release SQL contains no views")
    return tuple(sorted(views))


def _header(text: str) -> dict[str, str]:
    """상단 SQL comment의 세미콜론 구분 release metadata를 읽는다."""

    fields: dict[str, str] = {}
    for line in text.splitlines()[:12]:
        stripped = line.strip()
        if not stripped.startswith("--"):
            continue
        for item in stripped[2:].split(";"):
            key, separator, value = item.strip().partition("=")
            if separator and key and value:
                fields[key.strip()] = value.strip()
    return fields


def _release_document(manifest_path: Path) -> tuple[dict[str, Any], Path]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        raise ValueError("release manifest shape is invalid")
    release_root = manifest_path.parent.resolve()
    for item in manifest["files"]:
        if not isinstance(item, dict):
            raise ValueError("release file receipt is invalid")
        relative = item.get("relative_path")
        expected = item.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise ValueError("release file receipt is invalid")
        path = (release_root / relative).resolve(strict=True)
        if release_root not in path.parents:
            raise ValueError("release file escaped its directory")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected.casefold():
            raise ValueError(f"release checksum mismatch: {relative}")
    return manifest, release_root


def build_plan(manifest_path: Path, schema: str) -> dict[str, object]:
    """release metadata와 AST에서 순서·필수 DDL·검증 파일·View identity를 만든다."""

    manifest, release_root = _release_document(manifest_path.resolve(strict=True))
    release_id = str(manifest.get("release_id") or "")
    if not release_id:
        raise ValueError("release manifest has no release id")
    namespace = _namespace_parts(schema)
    entries: list[dict[str, object]] = []
    declared_views: set[str] = set()
    orders: set[int] = set()

    for receipt in manifest["files"]:
        relative = str(receipt["relative_path"])
        path = (release_root / relative).resolve(strict=True)
        text = path.read_text(encoding="utf-8-sig")
        header = _header(text)
        if not header.get("target_dbms", "").casefold().startswith("trino"):
            continue
        # manifest에 포함됐더라도 정식 release header가 없는 탐색용 SQL은 recovery
        # 실행 계획에 자동 편입하지 않는다.
        if "release_id" not in header:
            continue
        if header["release_id"] != release_id:
            raise ValueError(f"SQL release id differs from manifest: {relative}")
        order_text = header.get("execution_order", "")
        if not order_text.isdigit():
            raise ValueError(f"Trino SQL has no numeric execution order: {relative}")
        order = int(order_text)
        if order in orders:
            raise ValueError(f"Trino execution order is duplicated: {order}")
        orders.add(order)

        statements = tuple(
            statement
            for statement in parse(text, read="trino", error_level=ErrorLevel.RAISE)
            if statement is not None
        )
        if not statements:
            raise ValueError(f"Trino SQL contains no statements: {relative}")
        has_create = False
        has_query = False
        file_views: list[str] = []
        for statement in statements:
            if isinstance(statement, exp.Create):
                kind = str(statement.args.get("kind", "")).upper()
                parts = _target_parts(statement.this)
                if kind == "SCHEMA":
                    if parts != namespace:
                        raise ValueError(f"schema target escaped release namespace: {relative}")
                elif kind == "VIEW":
                    view = _view_identity(statement, schema)
                    if view in declared_views:
                        raise ValueError(f"view target is declared more than once: {view}")
                    declared_views.add(view)
                    file_views.append(view)
                else:
                    raise ValueError(f"unsupported Trino CREATE {kind}: {relative}")
                has_create = True
            elif isinstance(statement, exp.Comment):
                parts = _target_parts(statement.this)
                if len(parts) < 2 or parts[:2] != namespace:
                    raise ValueError(f"comment target escaped release namespace: {relative}")
            elif isinstance(statement, exp.Query):
                has_query = True
            elif isinstance(statement, exp.Use):
                continue
            else:
                raise ValueError(
                    f"unsupported Trino statement {type(statement).__name__}: {relative}"
                )
        entries.append(
            {
                "relative_path": relative.replace("\\", "/"),
                "execution_order": order,
                # PREFLIGHT_READONLY에는 최초 publish 전 namespace collision 검사처럼
                # recovery 재실행 시 의도적으로 실패하는 gate가 있을 수 있다.
                "mode": (
                    "required"
                    if has_create
                    else "preflight"
                    if header.get("script_type") == "PREFLIGHT_READONLY"
                    else "validation"
                ),
                "script_type": header.get("script_type", ""),
                "contains_query": has_query,
                "views": sorted(file_views),
            }
        )

    entries.sort(key=lambda item: (int(item["execution_order"]), str(item["relative_path"])))
    if not entries or not declared_views:
        raise ValueError("release has no executable Trino serving plan")
    expected_views = int((manifest.get("expected") or {}).get("serving_views", -1))
    if len(declared_views) != expected_views:
        raise ValueError("release View declarations differ from manifest expected count")
    return {
        "release_id": release_id,
        "schema": schema,
        "view_count": len(declared_views),
        "views": sorted(declared_views),
        "files": entries,
    }


def main() -> int:
    """manifest와 namespace를 받아 결정적인 recovery plan JSON을 출력한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--schema", required=True)
    args = parser.parse_args()
    plan = build_plan(args.manifest, args.schema)
    # Windows PowerShell 5.1 native stdout code page와 무관하게 경로를 보존한다.
    print(json.dumps(plan, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
