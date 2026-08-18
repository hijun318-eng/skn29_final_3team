#!/bin/sh
# 책임: 선택된 migration 경계를 완료한 뒤 ASGI process로 signal을 전달한다.
# migration 실패 시 HTTP server를 시작하지 않는다.
set -eu

# Migration failure must stop the container before the HTTP process starts;
# SKIP_MIGRATIONS is reserved for an externally governed migration workflow.
if [ "${SKIP_MIGRATIONS:-0}" != "1" ]; then
  alembic upgrade head
fi
# exec preserves signal delivery so Compose can drain the ASGI process cleanly.
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
