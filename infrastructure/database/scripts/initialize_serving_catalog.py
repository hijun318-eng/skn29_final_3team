"""Polaris 영속 catalog와 Trino 전용 최소권한 principal을 멱등 구성한다."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import httpx


REALM = "ANSWERVICE"
CATALOG = "answervice_serving"
PRINCIPAL_ROLE = "answervice_trino_role"
CATALOG_ROLE = "answervice_serving_admin"


def _read_env(path: Path) -> dict[str, str]:
    """중복·비표준 문법을 거부하며 dotenv를 secret 출력 없이 읽는다."""

    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"unsupported dotenv syntax at line {number}")
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        if not key or not key.replace("_", "a").isalnum() or key[0].isdigit():
            raise ValueError(f"unsupported dotenv key at line {number}")
        if key in values:
            raise ValueError(f"duplicate dotenv key: {key}")
        values[key] = value.strip().strip('"\'')
    return values


def _require(values: dict[str, str], names: tuple[str, ...]) -> None:
    """필수 설정과 placeholder를 Polaris 호출 전에 fail-closed 검증한다."""

    for name in names:
        value = values.get(name, "")
        if not value or value.startswith(("CHANGE_ME_", "REQUIRED_")):
            raise ValueError(f"deployment key is missing or placeholder: {name}")


def _assert_env_scope(path: Path, repository: Path, allow_local: bool) -> None:
    """운영은 외부 env만, 명시적 local mode는 gitignored env만 허용한다."""

    try:
        path.relative_to(repository)
    except ValueError:
        return
    if not allow_local:
        raise ValueError("repository-local env requires --allow-repository-local-development")
    result = subprocess.run(
        ["git", "-C", str(repository), "check-ignore", "-q", "--", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError("repository-local env must be covered by .gitignore")


def _set_env_values(path: Path, replacements: dict[str, str]) -> None:
    """Polaris가 발급한 opaque credential을 dotenv에 원자적으로 결속한다."""

    lines = path.read_text(encoding="utf-8-sig").splitlines()
    remaining = dict(replacements)
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].removeprefix("export ").strip() if "=" in stripped else ""
        if key in remaining:
            output.append(f"{key}={remaining.pop(key)}")
        else:
            output.append(line)
    output.extend(f"{key}={value}" for key, value in remaining.items())
    payload = "\r\n".join(output).rstrip("\r\n") + "\r\n"
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=".serving-catalog-env-", suffix=".tmp", dir=path.parent
    )
    os.close(file_descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(payload, encoding="utf-8", newline="")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _entity_name(document: Any, singular: str) -> str:
    """Management API의 entity wrapper 또는 direct entity에서 name을 읽는다."""

    if not isinstance(document, dict):
        return ""
    entity = document.get(singular, document)
    return str(entity.get("name", "")) if isinstance(entity, dict) else ""


def _document_contains(document: Any, key: str, expected: str) -> bool:
    """중첩 collection 응답에서 exact name/privilege read-back을 확인한다."""

    if isinstance(document, dict):
        if str(document.get(key, "")) == expected:
            return True
        return any(_document_contains(value, key, expected) for value in document.values())
    if isinstance(document, list):
        return any(_document_contains(value, key, expected) for value in document)
    return False


async def _request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    token: str,
    json_body: dict[str, Any] | None = None,
    accepted: tuple[int, ...] = (200, 201, 204),
) -> httpx.Response:
    """Bearer·realm 경계를 모든 management 요청에 동일하게 적용한다."""

    response = await client.request(
        method,
        path,
        headers={"Authorization": f"Bearer {token}", "Polaris-Realm": REALM},
        json=json_body,
    )
    if response.status_code not in accepted:
        raise RuntimeError(
            f"Polaris management request failed: {method} {path} -> {response.status_code}"
        )
    return response


async def _exists(
    client: httpx.AsyncClient, path: str, *, token: str, singular: str, name: str
) -> bool:
    """404만 미존재로 취급하고 다른 실패를 성공으로 흡수하지 않는다."""

    response = await client.get(
        path,
        headers={"Authorization": f"Bearer {token}", "Polaris-Realm": REALM},
    )
    if response.status_code == 404:
        return False
    if response.status_code != 200:
        raise RuntimeError(f"Polaris read-back failed: GET {path} -> {response.status_code}")
    if _entity_name(response.json(), singular) != name:
        raise RuntimeError(f"Polaris read-back identity mismatch: {path}")
    return True


async def _put_and_verify(
    client: httpx.AsyncClient,
    path: str,
    *,
    token: str,
    json_body: dict[str, Any],
    readback_key: str,
    expected_value: str,
) -> None:
    """멱등 PUT의 duplicate 응답도 live collection read-back이 맞을 때만 성공시킨다."""

    await _request(
        client,
        "PUT",
        path,
        token=token,
        json_body=json_body,
        accepted=(200, 201, 204, 409),
    )
    response = await _request(client, "GET", path, token=token)
    if not _document_contains(response.json(), readback_key, expected_value):
        raise RuntimeError(f"Polaris assignment read-back mismatch: {path}")


async def _configure(values: dict[str, str], env_path: Path) -> dict[str, object]:
    """Catalog·principal·role·grant를 생성한 뒤 Trino credential을 env에 저장한다."""

    port = int(values.get("SERVING_CATALOG_API_PORT", "18181"))
    base_url = f"http://127.0.0.1:{port}"
    timeout = httpx.Timeout(15.0, connect=5.0)
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout, trust_env=False) as client:
        token_response = await client.post(
            "/api/catalog/v1/oauth/tokens",
            headers={"Polaris-Realm": REALM},
            data={
                "grant_type": "client_credentials",
                "client_id": values["SERVING_CATALOG_ADMIN_CLIENT_ID"],
                "client_secret": values["SERVING_CATALOG_ADMIN_CLIENT_SECRET"],
                "scope": "PRINCIPAL_ROLE:ALL",
            },
        )
        if token_response.status_code != 200:
            raise RuntimeError(f"Polaris token request failed: {token_response.status_code}")
        token = str(token_response.json().get("access_token", ""))
        if not token:
            raise RuntimeError("Polaris token response has no access_token")

        catalog_path = f"/api/management/v1/catalogs/{CATALOG}"
        if not await _exists(client, catalog_path, token=token, singular="catalog", name=CATALOG):
            bucket = values["SERVING_OBJECT_STORE_BUCKET"]
            await _request(
                client,
                "POST",
                "/api/management/v1/catalogs",
                token=token,
                json_body={
                    "catalog": {
                        "name": CATALOG,
                        "type": "INTERNAL",
                        "readOnly": False,
                        "properties": {"default-base-location": f"s3://{bucket}"},
                        "storageConfigInfo": {
                            "storageType": "S3",
                            "allowedLocations": [f"s3://{bucket}"],
                            "endpoint": "http://serving-object-store:9000",
                            "endpointInternal": "http://serving-object-store:9000",
                            "pathStyleAccess": True,
                            "region": values["SERVING_OBJECT_STORE_REGION"],
                        },
                    }
                },
            )
            if not await _exists(client, catalog_path, token=token, singular="catalog", name=CATALOG):
                raise RuntimeError("Polaris catalog create read-back failed")

        principal = values["SERVING_CATALOG_TRINO_PRINCIPAL"]
        principal_path = f"/api/management/v1/principals/{principal}"
        new_credentials: dict[str, str] | None = None
        if not await _exists(
            client, principal_path, token=token, singular="principal", name=principal
        ):
            response = await _request(
                client,
                "POST",
                "/api/management/v1/principals",
                token=token,
                json_body={"principal": {"name": principal, "properties": {}}},
            )
            credentials = response.json().get("credentials", {})
            client_id = str(credentials.get("clientId", ""))
            client_secret = str(credentials.get("clientSecret", ""))
            if not client_id or not client_secret:
                raise RuntimeError("Polaris principal create response has no credentials")
            new_credentials = {
                "SERVING_CATALOG_TRINO_CLIENT_ID": client_id,
                "SERVING_CATALOG_TRINO_CLIENT_SECRET": client_secret,
            }
        else:
            _require(
                values,
                ("SERVING_CATALOG_TRINO_CLIENT_ID", "SERVING_CATALOG_TRINO_CLIENT_SECRET"),
            )

        role_path = f"/api/management/v1/principal-roles/{PRINCIPAL_ROLE}"
        if not await _exists(
            client, role_path, token=token, singular="principalRole", name=PRINCIPAL_ROLE
        ):
            await _request(
                client,
                "POST",
                "/api/management/v1/principal-roles",
                token=token,
                json_body={"principalRole": {"name": PRINCIPAL_ROLE, "properties": {}}},
            )

        catalog_role_path = (
            f"/api/management/v1/catalogs/{CATALOG}/catalog-roles/{CATALOG_ROLE}"
        )
        if not await _exists(
            client,
            catalog_role_path,
            token=token,
            singular="catalogRole",
            name=CATALOG_ROLE,
        ):
            await _request(
                client,
                "POST",
                f"/api/management/v1/catalogs/{CATALOG}/catalog-roles",
                token=token,
                json_body={"catalogRole": {"name": CATALOG_ROLE, "properties": {}}},
            )

        await _put_and_verify(
            client,
            f"/api/management/v1/principals/{principal}/principal-roles",
            token=token,
            json_body={"principalRole": {"name": PRINCIPAL_ROLE}},
            readback_key="name",
            expected_value=PRINCIPAL_ROLE,
        )
        await _put_and_verify(
            client,
            f"/api/management/v1/principal-roles/{PRINCIPAL_ROLE}/catalog-roles/{CATALOG}",
            token=token,
            json_body={"catalogRole": {"name": CATALOG_ROLE}},
            readback_key="name",
            expected_value=CATALOG_ROLE,
        )
        await _put_and_verify(
            client,
            f"/api/management/v1/catalogs/{CATALOG}/catalog-roles/{CATALOG_ROLE}/grants",
            token=token,
            json_body={"type": "catalog", "privilege": "CATALOG_MANAGE_CONTENT"},
            readback_key="privilege",
            expected_value="CATALOG_MANAGE_CONTENT",
        )

    if new_credentials:
        _set_env_values(env_path, new_credentials)
    return {
        "status": "CONFIGURED",
        "catalog": CATALOG,
        "principal": values["SERVING_CATALOG_TRINO_PRINCIPAL"],
        "principal_role": PRINCIPAL_ROLE,
        "catalog_role": CATALOG_ROLE,
        "credential_created": bool(new_credentials),
        "secret_values_logged": False,
    }


def main() -> int:
    """명시된 env scope를 검증하고 Polaris management 구성을 실행한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--allow-repository-local-development", action="store_true")
    args = parser.parse_args()
    env_path = args.env_file.resolve(strict=True)
    repository = Path(__file__).resolve().parents[3]
    _assert_env_scope(env_path, repository, args.allow_repository_local_development)
    values = _read_env(env_path)
    _require(
        values,
        (
            "SERVING_CATALOG_ADMIN_CLIENT_ID",
            "SERVING_CATALOG_ADMIN_CLIENT_SECRET",
            "SERVING_CATALOG_TRINO_PRINCIPAL",
            "SERVING_OBJECT_STORE_BUCKET",
            "SERVING_OBJECT_STORE_REGION",
        ),
    )
    result = asyncio.run(_configure(values, env_path))
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
