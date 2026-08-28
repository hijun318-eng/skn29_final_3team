"""Windows Selector event loop로 로컬 E2E Backend를 실행한다."""

from __future__ import annotations

import asyncio

import uvicorn


if __name__ == "__main__":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    uvicorn.run("app.main:app", host="127.0.0.1", port=18002, loop="none")
