from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID

from app.contracts import Role


ACCESS_POLICY_VERSION = "ACCESS-POLICY-v1.0.0"


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
