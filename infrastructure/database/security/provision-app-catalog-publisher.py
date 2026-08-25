"""외부 deployment env에 catalog publisher 자격증명을 안전하게 결속한다."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
from pathlib import Path


DEFAULT_PUBLISHER_USER = "app_catalog_publisher"
ROLE_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{2,62}$")
ENV_PATTERN = re.compile(
    r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$"
)


def _is_placeholder(value: str) -> bool:
    canonical = value.strip().upper()
    return not canonical or canonical.startswith(("CHANGE_ME_", "REQUIRED_"))


def _read_env(path: Path) -> tuple[list[str], dict[str, str]]:
    """중복·비표준 dotenv를 거부하고 원문 행과 값을 함께 읽는다."""

    lines = path.read_text(encoding="utf-8-sig").splitlines()
    values: dict[str, str] = {}
    for number, raw in enumerate(lines, 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        match = ENV_PATTERN.fullmatch(raw)
        if match is None:
            raise ValueError(f"unsupported dotenv syntax at line {number}")
        key = match.group(1)
        if key in values:
            raise ValueError(f"duplicate dotenv key: {key}")
        value = match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return lines, values


def _assert_env_scope(path: Path, repository: Path, allow_local: bool) -> None:
    """운영은 repository 밖 env만, 명시적 개발 모드는 gitignored env만 허용한다."""

    if path != repository and repository not in path.parents:
        return
    if not allow_local:
        raise ValueError(
            "repository-local env requires --allow-repository-local-development"
        )
    ignored = subprocess.run(
        ["git", "-C", str(repository), "check-ignore", "-q", "--", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if ignored.returncode != 0:
        raise ValueError("repository-local env must be covered by .gitignore")


def _render_env(lines: list[str], replacements: dict[str, str]) -> str:
    remaining = dict(replacements)
    output: list[str] = []
    for line in lines:
        match = ENV_PATTERN.fullmatch(line)
        key = match.group(1) if match else ""
        if key in remaining:
            output.append(f"{key}={remaining.pop(key)}")
        else:
            output.append(line)
    output.extend(f"{key}={value}" for key, value in remaining.items())
    return "\r\n".join(output).rstrip("\r\n") + "\r\n"


def _atomic_replace(path: Path, original: str, payload: str) -> None:
    """같은 directory의 임시 파일을 fsync한 뒤 원본이 그대로일 때만 교체한다."""

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".catalog-publisher-env-", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if path.read_text(encoding="utf-8-sig") != original:
            raise RuntimeError("deployment env changed concurrently; nothing was replaced")
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def provision(
    env_path: Path,
    *,
    repository: Path,
    allow_local: bool = False,
    rotate_password: bool = False,
) -> dict[str, object]:
    """publisher role/password를 멱등 생성하고 secret 없는 receipt만 반환한다."""

    path = env_path.resolve(strict=True)
    repository = repository.resolve()
    _assert_env_scope(path, repository, allow_local)
    original = path.read_text(encoding="utf-8-sig")
    lines, values = _read_env(path)

    runtime_user = values.get("APP_DB_USER", "")
    migration_user = values.get("APP_MIGRATION_USER", "")
    for key, role in (
        ("APP_DB_USER", runtime_user),
        ("APP_MIGRATION_USER", migration_user),
    ):
        if _is_placeholder(role) or ROLE_PATTERN.fullmatch(role) is None:
            raise ValueError(f"deployment role is missing or invalid: {key}")

    configured_publisher = values.get("APP_CATALOG_PUBLISHER_USER", "")
    publisher_user = (
        DEFAULT_PUBLISHER_USER
        if _is_placeholder(configured_publisher)
        else configured_publisher
    )
    if ROLE_PATTERN.fullmatch(publisher_user) is None:
        raise ValueError("APP_CATALOG_PUBLISHER_USER is invalid")
    if publisher_user in {runtime_user, migration_user}:
        raise ValueError("runtime, migration, and catalog publisher roles must differ")

    configured_password = values.get("APP_CATALOG_PUBLISHER_PASSWORD", "")
    password_generated = rotate_password or _is_placeholder(configured_password)
    if password_generated:
        publisher_password = secrets.token_urlsafe(32)
    else:
        publisher_password = configured_password
        if len(publisher_password) < 12:
            raise ValueError(
                "APP_CATALOG_PUBLISHER_PASSWORD must contain at least 12 characters"
            )

    replacements: dict[str, str] = {}
    if configured_publisher != publisher_user:
        replacements["APP_CATALOG_PUBLISHER_USER"] = publisher_user
    if password_generated:
        replacements["APP_CATALOG_PUBLISHER_PASSWORD"] = publisher_password
    if replacements:
        payload = _render_env(lines, replacements)
        _atomic_replace(path, original, payload)
        _, readback = _read_env(path)
        if (
            readback.get("APP_CATALOG_PUBLISHER_USER") != publisher_user
            or readback.get("APP_CATALOG_PUBLISHER_PASSWORD") != publisher_password
        ):
            raise RuntimeError("catalog publisher credential read-back mismatch")

    return {
        "status": "PROVISIONED" if replacements else "UNCHANGED",
        "publisher_user": publisher_user,
        "password_generated": password_generated,
        "password_rotated": bool(rotate_password),
        "secret_values_logged": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--allow-repository-local-development", action="store_true")
    parser.add_argument("--rotate-credential", action="store_true")
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[3]
    receipt = provision(
        args.env_file,
        repository=repository,
        allow_local=args.allow_repository_local_development,
        rotate_password=args.rotate_credential,
    )
    print(json.dumps(receipt, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
