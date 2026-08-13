#!/bin/sh
set -eu

if [ "${SKIP_MIGRATIONS:-0}" != "1" ]; then
  alembic upgrade head
fi
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
