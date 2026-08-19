"""DataHub dataset metadata와 ``semanticContent`` aspect 값을 엄격하게 검증한다."""

from __future__ import annotations

import math
import hashlib
import struct
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


EXPECTED_MODEL = "nomic-embed-text"
EXPECTED_MODEL_KEY = "nomic_embed_text"
EXPECTED_DIMENSION = 768
SEMANTIC_INDEX = "datasetindex_v2_semantic"
CHUNK_SIZE = 1_800
CHUNKING_STRATEGY = "fixed_1800_chars_boundary_aware_v1"


class SemanticContentError(RuntimeError):
    """live metadata 또는 생성된 semantic content가 v1.7 계약을 위반했음을 나타낸다."""


@dataclass(frozen=True)
class GlossaryTerm:
    """semantic document 증거로 사용하는 해석 완료 활성 glossary term이다."""

    urn: str
    name: str
    description: str | None


@dataclass(frozen=True)
class DatasetField:
    """live schema field 하나와 해당 field의 거버넌스 glossary 연결을 표현한다."""

    name: str
    native_type: str | None
    description: str | None
    term_urns: tuple[str, ...]


@dataclass(frozen=True)
class DatasetMetadata:
    """DataHub GraphQL에서 발견해 정규화한 활성 dataset metadata를 표현한다."""

    urn: str
    name: str
    qualified_name: str | None
    description: str | None
    domain_name: str | None
    domain_description: str | None
    term_urns: tuple[str, ...]
    fields: tuple[DatasetField, ...]


@dataclass(frozen=True)
class DatasetDocument:
    """live metadata에서 결정론적으로 만든 검색 text와 probe를 표현한다."""

    urn: str
    text: str
    probe_query: str


@dataclass(frozen=True)
class DocumentChunk:
    """embedding vector 하나에 위치 기준으로 결합된 안정적인 문자열 조각이다."""

    position: int
    character_offset: int
    text: str


def require_sha256(value: str) -> str:
    """완전한 artifact digest를 검증하고 정규 SHA256 표현으로 변환한다."""

    prefix, separator, hexadecimal = value.strip().lower().partition(":")
    if prefix != "sha256" or separator != ":" or len(hexadecimal) != 64:
        raise SemanticContentError("Ollama model digest must be a full sha256 digest")
    try:
        int(hexadecimal, 16)
    except ValueError as exc:
        raise SemanticContentError("Ollama model digest must be hexadecimal") from exc
    return f"sha256:{hexadecimal}"


def normalize_model(value: str) -> str:
    """Ollama model 이름을 identity 비교 목적으로만 정규화한다."""

    model = value.strip()
    if not model:
        raise SemanticContentError("Ollama embedding model is required")
    return model if ":" in model else f"{model}:latest"


def require_supported_model(value: str) -> str:
    """배포된 DataHub vector mapping과 호환되지 않는 model을 거부한다."""

    if normalize_model(value) != normalize_model(EXPECTED_MODEL):
        raise SemanticContentError(
            f"DataHub v1.7 semantic mapping requires model {EXPECTED_MODEL}"
        )
    return value.strip()


def require_dataset_urn(value: object) -> str:
    """크기가 제한된 DataHub dataset URN wire 표현을 검증한다."""

    if (
        not isinstance(value, str)
        or not value.startswith("urn:li:dataset:(")
        or not value.endswith(")")
        or len(value) > 2_048
    ):
        raise SemanticContentError("DataHub returned an invalid dataset URN")
    return value


def _text(value: object, label: str, *, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise SemanticContentError(f"DataHub {label} must be text")
    normalized = " ".join(value.split())
    if required and not normalized:
        raise SemanticContentError(f"DataHub {label} must not be empty")
    return normalized or None


def _term_urns(value: object, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    terms = value.get("terms") if isinstance(value, Mapping) else None
    if not isinstance(terms, list):
        raise SemanticContentError(f"DataHub {label} glossary associations are invalid")
    result: list[str] = []
    for association in terms:
        term = association.get("term") if isinstance(association, Mapping) else None
        urn = term.get("urn") if isinstance(term, Mapping) else None
        if not isinstance(urn, str) or not urn.startswith("urn:li:glossaryTerm:"):
            raise SemanticContentError(f"DataHub {label} has an invalid glossary term URN")
        if urn in result:
            raise SemanticContentError(f"DataHub {label} repeats a glossary term URN")
        result.append(urn)
    return tuple(result)


def parse_dataset(value: object, expected_urn: str) -> DatasetMetadata | None:
    """GraphQL dataset 하나를 해석하며 soft-delete dataset은 명시적으로 제외한다."""

    if not isinstance(value, Mapping) or require_dataset_urn(value.get("urn")) != expected_urn:
        raise SemanticContentError("DataHub dataset detail identity does not match search")
    status = value.get("status")
    if not isinstance(status, Mapping) or not isinstance(status.get("removed"), bool):
        raise SemanticContentError("DataHub dataset removal status is missing")
    if status["removed"]:
        return None
    properties = value.get("properties")
    if properties is None:
        properties = {}
    if not isinstance(properties, Mapping):
        raise SemanticContentError("DataHub active dataset properties are malformed")
    name = _text(properties.get("name") or value.get("name"), "dataset name", required=True)
    domain_name: str | None = None
    domain_description: str | None = None
    domain = value.get("domain")
    if domain is not None:
        domain_value = domain.get("domain") if isinstance(domain, Mapping) else None
        if domain_value is None and isinstance(domain, Mapping):
            domain = None
        elif domain_value is None:
            raise SemanticContentError("DataHub dataset domain is malformed")
    if domain is not None:
        domain_value = domain["domain"]
        domain_properties = (
            domain_value.get("properties") if isinstance(domain_value, Mapping) else None
        )
        if not isinstance(domain_properties, Mapping):
            raise SemanticContentError("DataHub dataset domain is malformed")
        domain_name = _text(domain_properties.get("name"), "domain name", required=True)
        domain_description = _text(domain_properties.get("description"), "domain description")
    fields: list[DatasetField] = []
    schema = value.get("schemaMetadata")
    if schema is not None:
        raw_fields = schema.get("fields") if isinstance(schema, Mapping) else None
        if not isinstance(raw_fields, list):
            raise SemanticContentError("DataHub dataset schema fields are malformed")
        seen_fields: set[str] = set()
        for raw_field in raw_fields:
            if not isinstance(raw_field, Mapping):
                raise SemanticContentError("DataHub dataset schema field is malformed")
            field_name = _text(raw_field.get("fieldPath"), "field path", required=True)
            if field_name in seen_fields:
                raise SemanticContentError("DataHub dataset repeats a schema field path")
            seen_fields.add(field_name)
            fields.append(
                DatasetField(
                    name=field_name,
                    native_type=_text(raw_field.get("nativeDataType"), "field native type"),
                    description=_text(raw_field.get("description"), "field description"),
                    term_urns=_term_urns(raw_field.get("glossaryTerms"), "field"),
                )
            )
    return DatasetMetadata(
        urn=expected_urn,
        name=name,
        qualified_name=_text(properties.get("qualifiedName"), "qualified name"),
        description=_text(properties.get("description"), "dataset description"),
        domain_name=domain_name,
        domain_description=domain_description,
        term_urns=_term_urns(value.get("glossaryTerms"), "dataset"),
        fields=tuple(fields),
    )


def parse_glossary_term(value: object, expected_urn: str) -> GlossaryTerm:
    """dataset field가 참조한 정확한 활성 glossary term 하나를 해석한다."""

    if not isinstance(value, Mapping) or value.get("urn") != expected_urn:
        raise SemanticContentError("DataHub glossary term identity does not match its reference")
    status = value.get("status")
    if (
        value.get("exists") is not True
        or not isinstance(status, Mapping)
        or status.get("removed") is not False
    ):
        raise SemanticContentError("DataHub dataset references a missing or removed glossary term")
    info = value.get("glossaryTermInfo")
    if not isinstance(info, Mapping):
        raise SemanticContentError("DataHub glossary term properties are missing")
    return GlossaryTerm(
        urn=expected_urn,
        name=_text(info.get("name"), "glossary term name", required=True),
        description=_text(info.get("description"), "glossary term description"),
    )


def referenced_term_urns(datasets: Sequence[DatasetMetadata]) -> tuple[str, ...]:
    """모든 dataset document에 필요한 중복 없는 glossary term 폐쇄 집합을 반환한다."""

    urns = {
        urn
        for dataset in datasets
        for urn in dataset.term_urns
    }
    urns.update(
        urn
        for dataset in datasets
        for field in dataset.fields
        for urn in field.term_urns
    )
    return tuple(sorted(urns))


def build_document(
    dataset: DatasetMetadata,
    terms: Mapping[str, GlossaryTerm],
) -> DatasetDocument:
    """live metadata와 해석된 term만 사용해 검색 가능한 text를 렌더링한다."""

    lines = [f"Dataset name: {dataset.name}", f"Dataset URN: {dataset.urn}"]
    if dataset.qualified_name:
        lines.append(f"Qualified name: {dataset.qualified_name}")
    if dataset.description:
        lines.append(f"Description: {dataset.description}")
    if dataset.domain_name:
        domain = dataset.domain_name
        if dataset.domain_description:
            domain = f"{domain} — {dataset.domain_description}"
        lines.append(f"Domain: {domain}")
    for urn in dataset.term_urns:
        term = terms.get(urn)
        if term is None:
            raise SemanticContentError("A dataset glossary term was not resolved")
        suffix = f" — {term.description}" if term.description else ""
        lines.append(f"Glossary term: {term.name}{suffix}")
    for field in dataset.fields:
        parts = [f"Field: {field.name}"]
        if field.native_type:
            parts.append(f"type: {field.native_type}")
        if field.description:
            parts.append(f"description: {field.description}")
        field_terms: list[str] = []
        for urn in field.term_urns:
            term = terms.get(urn)
            if term is None:
                raise SemanticContentError("A field glossary term was not resolved")
            field_terms.append(term.name)
        if field_terms:
            parts.append(f"glossary terms: {', '.join(field_terms)}")
        lines.append("; ".join(parts))
    text = "\n".join(lines)
    probe = dataset.description or dataset.qualified_name or dataset.name
    return DatasetDocument(dataset.urn, text, probe[:256])


def chunk_document(text: str, max_characters: int = CHUNK_SIZE) -> tuple[DocumentChunk, ...]:
    """내용 손실 없이 안전한 경계에서 text를 결정론적으로 분할한다."""

    if not text or max_characters < 128:
        raise SemanticContentError("Semantic document text and a safe chunk bound are required")
    chunks: list[DocumentChunk] = []
    cursor = 0
    while cursor < len(text):
        end = min(cursor + max_characters, len(text))
        if end < len(text):
            minimum = cursor + max_characters // 2
            boundary = max(text.rfind("\n", minimum, end), text.rfind(" ", minimum, end))
            if boundary >= minimum:
                end = boundary
        while cursor < end and text[cursor].isspace():
            cursor += 1
        chunk_text = text[cursor:end].rstrip()
        if not chunk_text:
            raise SemanticContentError("Semantic chunking produced an empty chunk")
        chunks.append(DocumentChunk(len(chunks), cursor, chunk_text))
        cursor = end
    return tuple(chunks)


def validated_vector(value: object) -> list[float]:
    """DataHub가 요구하는 정확한 크기의 유한 float vector만 허용한다."""

    if not isinstance(value, list) or len(value) != EXPECTED_DIMENSION:
        raise SemanticContentError(
            f"Ollama vector dimension must equal {EXPECTED_DIMENSION}"
        )
    if any(
        isinstance(item, bool)
        or not isinstance(item, (int, float))
        or not math.isfinite(item)
        or abs(item) > 3.4028235e38
        for item in value
    ):
        raise SemanticContentError("Ollama embedding vector must contain finite numbers")
    return [float(item) for item in value]


def model_version(model: str, digest: str) -> str:
    """논리 model 이름을 불변 artifact digest에 결합한 version을 만든다."""

    return f"ollama/{normalize_model(require_supported_model(model))}@{require_sha256(digest)}"


def model_data(
    chunks: Sequence[DocumentChunk],
    vectors: Sequence[object],
    *,
    model: str,
    digest: str,
    generated_at: int,
) -> dict[str, Any]:
    """각 chunk를 vector 하나 및 생성 provenance와 순서대로 결합한다."""

    if not isinstance(generated_at, int) or isinstance(generated_at, bool) or generated_at <= 0:
        raise SemanticContentError("Embedding generation timestamp must be a positive integer")
    if not chunks or len(chunks) != len(vectors):
        raise SemanticContentError("Every semantic chunk must have exactly one vector")
    values = []
    for chunk, vector in zip(chunks, vectors, strict=True):
        values.append(
            {
                "position": chunk.position,
                "vector": validated_vector(vector),
                "characterOffset": chunk.character_offset,
                "characterLength": len(chunk.text),
                "text": chunk.text,
            }
        )
    return {
        "modelVersion": model_version(model, digest),
        "generatedAt": generated_at,
        "chunkingStrategy": CHUNKING_STRATEGY,
        "totalChunks": len(values),
        "chunks": values,
    }


def same_model_data(actual: object, expected: Mapping[str, Any]) -> bool:
    """저장된 model data를 Elasticsearch float32 정밀도 기준으로 비교한다."""

    if not isinstance(actual, Mapping):
        return False
    actual_copy = dict(actual)
    expected_copy = dict(expected)
    actual_generated = actual_copy.pop("generatedAt", None)
    expected_copy.pop("generatedAt", None)
    if (
        not isinstance(actual_generated, int)
        or isinstance(actual_generated, bool)
        or actual_generated <= 0
    ):
        return False
    try:
        return _float32_model_data(actual_copy) == _float32_model_data(expected_copy)
    except SemanticContentError:
        return False


def _float32_model_data(value: Mapping[str, Any]) -> dict[str, Any]:
    canonical = dict(value)
    chunks = canonical.get("chunks")
    if not isinstance(chunks, list):
        raise SemanticContentError("Embedding model chunks are malformed")
    canonical_chunks: list[dict[str, Any]] = []
    for chunk in chunks:
        if not isinstance(chunk, Mapping):
            raise SemanticContentError("Embedding model chunk is malformed")
        canonical_chunk = dict(chunk)
        canonical_chunk["vector"] = tuple(
            struct.pack("!f", item) for item in validated_vector(chunk.get("vector"))
        )
        canonical_chunks.append(canonical_chunk)
    canonical["chunks"] = canonical_chunks
    return canonical


def indexed_model_fingerprint(value: object) -> str:
    """JSON float 표기에 의존하지 않고 indexed text와 float32 vector를 결합해 지문을 만든다."""

    if not isinstance(value, Mapping):
        raise SemanticContentError("Indexed embedding model data is malformed")
    model = value.get("modelVersion")
    strategy = value.get("chunkingStrategy")
    count = value.get("totalChunks")
    chunks = value.get("chunks")
    if (
        not isinstance(model, str)
        or not isinstance(strategy, str)
        or not isinstance(count, int)
        or isinstance(count, bool)
        or not isinstance(chunks, list)
        or count != len(chunks)
    ):
        raise SemanticContentError("Indexed embedding model metadata is malformed")
    digest = hashlib.sha256()
    digest.update(model.encode("utf-8"))
    digest.update(strategy.encode("utf-8"))
    digest.update(struct.pack("!I", count))
    for position, chunk in enumerate(chunks):
        if not isinstance(chunk, Mapping) or chunk.get("position") != position:
            raise SemanticContentError("Indexed embedding chunk position is malformed")
        text = chunk.get("text")
        offset = chunk.get("characterOffset")
        length = chunk.get("characterLength")
        if (
            not isinstance(text, str)
            or not isinstance(offset, int)
            or isinstance(offset, bool)
            or not isinstance(length, int)
            or isinstance(length, bool)
            or length != len(text)
        ):
            raise SemanticContentError("Indexed embedding chunk content is malformed")
        digest.update(struct.pack("!II", offset, length))
        digest.update(text.encode("utf-8"))
        for item in validated_vector(chunk.get("vector")):
            digest.update(struct.pack("!f", item))
    return f"sha256:{digest.hexdigest()}"
