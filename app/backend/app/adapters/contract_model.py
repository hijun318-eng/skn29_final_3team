"""분리된 모델 context·schema·transport 구현을 기존 ``ContractModelAdapter`` import 경계로 공개한다.

Compatibility facade for the production model adapter modules.
"""

from app.adapters.model_adapter import ContractModelAdapter, sql_fingerprint as _sql_fingerprint
from app.adapters.model_schemas import (
    canonical_model_input as _canonical_model_input,
    openai_payload as _openai_payload,
    qwen_payload as _qwen_payload,
    response_schema as _response_schema,
    serving_schema as _serving_schema,
)
from app.adapters.model_transport import (
    OpenAITransport,
    RoutedProductionModelClient,
    _request_json,
    openai_transport,
)


__all__ = [
    "ContractModelAdapter",
    "OpenAITransport",
    "RoutedProductionModelClient",
    "openai_transport",
]
