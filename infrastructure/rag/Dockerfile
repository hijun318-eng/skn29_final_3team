FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace \
    PIP_NO_CACHE_DIR=1

WORKDIR /workspace

ARG RAG_INCLUDE_QWEN=0
COPY infrastructure/rag/requirements*.txt infrastructure/rag/
RUN pip install --disable-pip-version-check -r infrastructure/rag/requirements.txt \
    && if [ "$RAG_INCLUDE_QWEN" = "1" ]; then pip install --disable-pip-version-check -r infrastructure/rag/requirements-qwen.txt; fi

COPY src/ ./src/
COPY config/rag/ ./config/rag/
COPY data/rag/ ./data/rag/
COPY evals/testsets/rag/ ./evals/testsets/rag/
COPY infrastructure/rag/db/init/ ./infrastructure/rag/db/init/
COPY infrastructure/rag/entrypoint.sh /usr/local/bin/rag-entrypoint

RUN chmod 0555 /usr/local/bin/rag-entrypoint \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /workspace/evals/runs/rag /backups/rag \
    && chown -R appuser:appuser /workspace /backups/rag

USER appuser
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/rag-entrypoint"]
