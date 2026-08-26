"""Answervice 내부업무매뉴얼 RAG 핵심 패키지."""

from typing import Any

__all__ = ["VectorRagApplication"]


def __getattr__(name: str) -> Any:
    if name == "VectorRagApplication":
        from .vector_application import VectorRagApplication

        return VectorRagApplication
    raise AttributeError(name)
