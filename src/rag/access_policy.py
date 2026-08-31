from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class AccessDeniedError(ValueError):
    """Raised when a caller role is not registered in the server policy."""


@dataclass(frozen=True)
class SearchDecision:
    role: str
    allow_unresolved_validity: bool
    minimum_score: float
    candidate_minimum_score: float
    top_k: int


class SearchAccessPolicy:
    def __init__(
        self,
        known_roles: frozenset[str],
        unresolved_roles: frozenset[str],
        default_minimum_score: float,
        candidate_minimum_score: float,
        maximum_top_k: int,
    ) -> None:
        self._known_roles = known_roles
        self._unresolved_roles = unresolved_roles
        self._default_minimum_score = default_minimum_score
        self._candidate_minimum_score = candidate_minimum_score
        self._maximum_top_k = maximum_top_k

    @classmethod
    def load(cls, path: Path) -> "SearchAccessPolicy":
        payload = json.loads(path.read_text(encoding="utf-8"))
        known_roles = frozenset(str(role) for role in payload["known_roles"])
        unresolved_roles = frozenset(
            str(role) for role in payload["unresolved_validity_roles"]
        )
        if not unresolved_roles.issubset(known_roles):
            raise ValueError("Unresolved-validity roles must be registered roles")
        return cls(
            known_roles=known_roles,
            unresolved_roles=unresolved_roles,
            default_minimum_score=float(payload["default_minimum_score"]),
            candidate_minimum_score=float(payload["candidate_minimum_score"]),
            maximum_top_k=int(payload["maximum_top_k"]),
        )

    def decide(self, role: str, top_k: int | None = None) -> SearchDecision:
        normalized_role = role.strip().upper()
        if normalized_role not in self._known_roles:
            raise AccessDeniedError(f"Unregistered role: {normalized_role}")
        bounded_top_k = min(max(top_k or 5, 1), self._maximum_top_k)
        return SearchDecision(
            role=normalized_role,
            allow_unresolved_validity=normalized_role in self._unresolved_roles,
            minimum_score=self._default_minimum_score,
            candidate_minimum_score=self._candidate_minimum_score,
            top_k=bounded_top_k,
        )
