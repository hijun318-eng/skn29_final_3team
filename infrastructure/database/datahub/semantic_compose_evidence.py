"""로컬 GMS와 점검한 Elasticsearch의 결합을 live Docker Compose 증거로 검증한다."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import urlsplit

from semantic_deployment_evidence import VerificationError


EXPECTED_GMS_ENVIRONMENT = {
    "ELASTICSEARCH_HOST": "semantic-elasticsearch",
    "ELASTICSEARCH_IMPLEMENTATION": "elasticsearch",
    "ELASTICSEARCH_PORT": "9200",
    "ELASTICSEARCH_SHIM_ENABLED": "true",
    "ELASTICSEARCH_SHIM_ENGINE_TYPE": "ELASTICSEARCH_8",
    "SEARCH_SERVICE_SEMANTIC_SEARCH_ENABLED": "true",
    "ELASTICSEARCH_SEMANTIC_SEARCH_ENABLED": "true",
    "ELASTICSEARCH_SEMANTIC_SEARCH_ENTITIES": "document,dataset",
}


def _safe_project_name(value: str) -> str:
    allowed = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_-")
    if not value or len(value) > 63 or any(character.lower() not in allowed for character in value):
        raise VerificationError("Compose project name is invalid")
    return value


def _service_document(documents: list[Any], project: str, service: str) -> dict[str, Any]:
    matches = [
        document
        for document in documents
        if isinstance(document, dict)
        and document.get("Config", {}).get("Labels", {}).get("com.docker.compose.project")
        == project
        and document.get("Config", {}).get("Labels", {}).get("com.docker.compose.service")
        == service
    ]
    if len(matches) != 1:
        raise VerificationError(f"Compose service {service} did not resolve to one container")
    if matches[0].get("State", {}).get("Running") is not True:
        raise VerificationError(f"Compose service {service} is not running")
    return matches[0]


def _environment(document: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in document.get("Config", {}).get("Env", []):
        if isinstance(item, str) and "=" in item:
            key, value = item.split("=", 1)
            values[key] = value
    return values


def _port_is_bound(document: dict[str, Any], container_port: str, host_url: str) -> bool:
    parsed = urlsplit(host_url)
    if parsed.port is None:
        return False
    bindings = document.get("NetworkSettings", {}).get("Ports", {}).get(container_port)
    if not isinstance(bindings, list):
        return False
    return any(
        isinstance(binding, dict)
        and binding.get("HostIp") in {"127.0.0.1", "::1"}
        and str(binding.get("HostPort")) == str(parsed.port)
        for binding in bindings
    )


def validate_compose_inspection(
    documents: list[Any],
    project: str,
    datahub_url: str,
    elasticsearch_url: str,
) -> dict[str, Any]:
    """inspect 문서에서 정확한 live Compose service와 endpoint 결합을 검증한다."""

    safe_project = _safe_project_name(project)
    gms = _service_document(documents, safe_project, "datahub-gms-quickstart")
    elasticsearch = _service_document(documents, safe_project, "semantic-elasticsearch")

    gms_environment = _environment(gms)
    drift = [
        key for key, expected in EXPECTED_GMS_ENVIRONMENT.items()
        if gms_environment.get(key) != expected
    ]
    if drift:
        raise VerificationError("GMS effective semantic-search environment has drifted")
    if not _port_is_bound(gms, "8443/tcp", datahub_url):
        raise VerificationError("probed DataHub URL is not bound to the inspected GMS container")
    if not _port_is_bound(elasticsearch, "9200/tcp", elasticsearch_url):
        raise VerificationError(
            "probed Elasticsearch URL is not bound to the inspected semantic container"
        )

    gms_networks = gms.get("NetworkSettings", {}).get("Networks", {})
    elasticsearch_networks = elasticsearch.get("NetworkSettings", {}).get("Networks", {})
    if not isinstance(gms_networks, dict) or not isinstance(elasticsearch_networks, dict):
        raise VerificationError("Compose network inspection is malformed")
    shared = sorted(set(gms_networks).intersection(elasticsearch_networks))
    resolvable = [
        network
        for network in shared
        if "semantic-elasticsearch"
        in (elasticsearch_networks[network].get("Aliases") or [])
    ]
    if len(resolvable) != 1:
        raise VerificationError("GMS cannot resolve the inspected Elasticsearch on one network")
    return {
        "compose_project": safe_project,
        "shared_network": resolvable[0],
        "gms_service": "datahub-gms-quickstart",
        "elasticsearch_service": "semantic-elasticsearch",
        "effective_search_host": gms_environment["ELASTICSEARCH_HOST"],
    }


async def verify_compose_deployment(
    project: str,
    datahub_url: str,
    elasticsearch_url: str,
) -> dict[str, Any]:
    """명시한 로컬 project를 inspect하고 검증된 deployment 증거를 반환한다."""

    safe_project = _safe_project_name(project)
    names = (
        f"{safe_project}-datahub-gms-quickstart-1",
        f"{safe_project}-semantic-elasticsearch-1",
    )
    try:
        process = await asyncio.create_subprocess_exec(
            "docker",
            "inspect",
            *names,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise VerificationError("Docker CLI is unavailable for deployment binding") from exc
    stdout, _stderr = await process.communicate()
    if process.returncode != 0:
        raise VerificationError("semantic Compose containers could not be inspected")
    try:
        documents = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError("Docker inspection returned malformed JSON") from exc
    if not isinstance(documents, list):
        raise VerificationError("Docker inspection returned a non-list value")
    return validate_compose_inspection(documents, safe_project, datahub_url, elasticsearch_url)
