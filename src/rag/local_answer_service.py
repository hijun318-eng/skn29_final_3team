from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .evidence_answer_composer import EvidenceBoundAnswerComposer


class ChatCompletionRequest(BaseModel):
    messages: list[dict[str, Any]] = Field(default_factory=list)


def create_app() -> FastAPI:
    app = FastAPI(title="Answervice Local Evidence Answer", version="1.0")
    composer = EvidenceBoundAnswerComposer()

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready() -> dict[str, str]:
        return {"status": "healthy"}

    @app.post("/v1/chat/completions")
    def chat_completion(request: ChatCompletionRequest) -> dict[str, Any]:
        content = json.dumps(composer.compose(request.messages), ensure_ascii=False)
        return {
            "id": "rag-local-answer",
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
        }

    return app


app = create_app()
