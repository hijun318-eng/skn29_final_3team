from __future__ import annotations

import json
import os
import hashlib
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from app.contracts import Role


ACCESS_POLICY_VERSION = "ACCESS-POLICY-v1.0.0"


@dataclass(frozen=True)
class AccessProfile:
    name: str
    datahub_principal: str
    credential_env: str
    domains: tuple[str, ...]
    trino_principal: str
    policy_version: str
    entitlement_hash: str

    def credential(self) -> str:
        value = os.getenv(self.credential_env, "").strip()
        if not value:
            raise RuntimeError("DataHub profile credential is unavailable")
        return value


def _path() -> Path:
    configured = os.getenv("ACCESS_POLICY_PATH")
    service = Path(__file__).resolve()
    candidates = [Path(configured)] if configured else []
    candidates += [Path.cwd() / "config/access-policy.yaml"]
    if len(service.parents) > 3:
        candidates.append(service.parents[3] / "config/access-policy.yaml")
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        raise RuntimeError("config/access-policy.yaml is required")
    return path


def _server_profiles_path() -> Path:
    configured = os.getenv("SERVER_ACCESS_PROFILES_PATH")
    service = Path(__file__).resolve()
    candidates = [Path(configured)] if configured else []
    candidates += [Path.cwd() / "config/server-access-profiles.v1.json"]
    if len(service.parents) > 3:
        candidates.append(service.parents[3] / "config/server-access-profiles.v1.json")
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        raise RuntimeError("server access profile contract is required")
    return path


def load_server_access_profiles() -> dict:
    try:
        path = _server_profiles_path()
        if path.stat().st_size > 1_048_576:
            raise ValueError
        contract = json.loads(path.read_text(encoding="utf-8"))
        profiles = contract["profiles"]
        if (
            contract.get("contract_version") != "SERVER-ACCESS-PROFILES-v1.0.0"
            or contract.get("default_effect") != "deny"
            or set(profiles) != {
                "pms_only", "crm_only", "pms_crm", "integrated_revenue",
                "integrated_operations",
            }
        ):
            raise ValueError
        for profile in profiles.values():
            if (
                set(profile) != {"domains", "datahub_actor", "datahub_token_env", "trino_principal"}
                or not profile["domains"]
                or not all(str(domain).startswith("urn:li:domain:") for domain in profile["domains"])
                or not str(profile["datahub_actor"]).startswith("urn:li:corpuser:")
                or not str(profile["datahub_token_env"]).startswith("DATAHUB_")
            ):
                raise ValueError
        return contract
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise RuntimeError("server access profile contract is invalid") from error


def load_access_policy() -> dict:
    try:
        path = _path()
        if path.stat().st_size > 1_048_576:
            raise ValueError
        policy = json.loads(path.read_text(encoding="utf-8"))
        if policy.get("policy_version") != ACCESS_POLICY_VERSION:
            raise ValueError
        mappings = policy["role_mappings"]
        groups = mappings["groups"]
        users = mappings["test_users"]
        if (
            not isinstance(groups, dict)
            or set(groups.values()) != {role.value for role in Role}
            or not isinstance(users, list)
            or not users
        ):
            raise ValueError
        subjects: set[UUID] = set()
        for item in users:
            if set(item) != {"subject", "group"} or item["group"] not in groups:
                raise ValueError
            subject = UUID(item["subject"])
            if subject in subjects:
                raise ValueError
            subjects.add(subject)
        profiles = policy["access_profiles"]
        server_profiles = load_server_access_profiles()["profiles"]
        if not isinstance(profiles, dict) or set(profiles) != set(server_profiles):
            raise ValueError
        for name, profile in profiles.items():
            if (
                not isinstance(name, str)
                or not name
                or set(profile) != {"allowed_roles"}
                or not isinstance(profile["allowed_roles"], list)
                or not set(profile["allowed_roles"]).issubset({role.value for role in Role})
            ):
                raise ValueError
        return policy
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise RuntimeError("access policy is invalid") from error


def test_seed_role(subject: UUID) -> Role | None:
    policy = load_access_policy()
    groups = policy["role_mappings"]["groups"]
    group = next(
        (item["group"] for item in policy["role_mappings"]["test_users"] if UUID(item["subject"]) == subject),
        None,
    )
    return Role(groups[group]) if group else None


def effective_access(subject: UUID, authenticated_role: Role) -> dict[str, str]:
    policy = load_access_policy()
    seeded = test_seed_role(subject)
    if os.getenv("AUTH_MODE", "release").strip().lower() == "test" and seeded != authenticated_role:
        raise RuntimeError("test principal does not match access policy")
    return {
        "policy_version": policy["policy_version"],
        "subject": str(subject),
        "role": authenticated_role.value,
        "mapping_source": "test_seed" if seeded else "release_principal",
    }


def resolve_access_profile(
    subject: UUID,
    authenticated_role: Role,
    requested: str | None,
) -> AccessProfile:
    policy = load_access_policy()
    name = requested.strip() if requested else "pms_only"
    raw = policy["access_profiles"].get(name)
    if raw is None or authenticated_role.value not in raw["allowed_roles"]:
        raise PermissionError("access profile is not allowed")
    server = load_server_access_profiles()["profiles"][name]
    allowed_domains = tuple(sorted(set(server["domains"])))
    canonical = ":".join(
        (str(subject), authenticated_role.value, name, policy["policy_version"], *allowed_domains)
    )
    return AccessProfile(
        name=name,
        datahub_principal=server["datahub_actor"],
        credential_env=server["datahub_token_env"],
        domains=allowed_domains,
        trino_principal=server["trino_principal"],
        policy_version=policy["policy_version"],
        entitlement_hash=hashlib.sha256(canonical.encode()).hexdigest(),
    )
