from __future__ import annotations

from fastapi import Request

from app.contracts import RequestContext


def request_context(request: Request) -> RequestContext:
    return RequestContext(request_id=request.state.request_id, trace_id=request.state.trace_id)
