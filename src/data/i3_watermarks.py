"""Deterministic watermark input for cache and report invalidation."""

from __future__ import annotations

from hashlib import sha256
from typing import Mapping


def watermark_fingerprint(values: Mapping[str, str]) -> str:
    canonical = "".join(f"{source}|{values[source]}\n" for source in sorted(values))
    return sha256(canonical.encode("utf-8")).hexdigest()


def changed_sources(previous: Mapping[str, str], current: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(
        source
        for source in sorted(previous.keys() | current.keys())
        if previous.get(source) != current.get(source)
    )
