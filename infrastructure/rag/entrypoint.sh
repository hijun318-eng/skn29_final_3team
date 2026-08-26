#!/bin/sh
set -eu

python -m src.rag.vector_cli migrate
exec uvicorn src.rag.api:create_app --factory --host 0.0.0.0 --port 8000
