"""RAG 검색 역할·점수·반환 개수에 적용할 접근 결정을 구성한다."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class AccessDeniedError(ValueError):
    """호출자 역할이 서버 정책에 등록되지 않아 검색을 거부했음을 나타낸다."""


@dataclass(frozen=True)
class SearchDecision:
    """역할별 유효성 허용 여부와 검색 후보·반환 한도를 고정한다."""

    role: str
    allow_unresolved_validity: bool
    minimum_score: float
    candidate_minimum_score: float
    top_k: int


class SearchAccessPolicy:
    """설정 파일의 역할 allowlist와 검색 제한을 검증해 적용한다."""

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
        """정책 JSON을 읽어 역할 집합과 수치 제한을 검증한 정책을 반환한다."""

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
        """검증 역할과 요청 개수를 확인하고 실행 가능한 검색 결정을 반환한다."""

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

    @property
    def known_roles(self) -> frozenset[str]:
        """corpus manifest 검증에 사용할 불변 역할 allowlist를 반환한다."""

        return self._known_roles
