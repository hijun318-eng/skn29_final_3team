"""ViewSpec 생성기와 소비자가 공유하는 canonical JSON·무결성 hash 계약이다."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any


def canonical_view_spec_json(spec_json: dict[str, Any]) -> str:
    """key 순서와 공백에 무관한 compact canonical ViewSpec JSON을 반환한다."""

    return json.dumps(
        spec_json,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    )


def view_spec_sha256(spec_json: dict[str, Any]) -> str:
    """canonical ViewSpec JSON의 불변 SHA-256을 계산한다."""

    return sha256(canonical_view_spec_json(spec_json).encode("utf-8")).hexdigest()
