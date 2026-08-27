# 책임: migration/runtime 코드를 동일한 digest 기반 Python image로 패키징한다.
# dependency 설치나 non-root ownership 설정이 실패하면 image 생성을 중단한다.
# The tag documents the supported Python line; the manifest digest makes CI and
# production rebuilds resolve the same base artifact.
FROM python:3.12-slim@sha256:dd29372629eeba2dd003fd9e9d35a5b8236c44727875a0364254b5127af88e65

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace \
    PIP_NO_CACHE_DIR=1

WORKDIR /workspace

COPY app/backend/requirements.txt app/backend/requirements.txt
COPY app/backend/requirements.lock.txt app/backend/requirements.lock.txt
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        fonts-noto-cjk libpango-1.0-0 libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --disable-pip-version-check \
        --constraint app/backend/requirements.lock.txt \
        -r app/backend/requirements.txt \
    && useradd --create-home --uid 10001 appuser

COPY --chown=appuser:appuser app/backend/ app/backend/
COPY --chown=appuser:appuser infrastructure/database/sql/ddl/00_answervice_app_postgresql.sql infrastructure/database/sql/ddl/00_answervice_app_postgresql.sql
COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser docs/ ./docs/
COPY --chown=appuser:appuser evals/__init__.py evals/metric_retrieval.py evals/metric_retrieval_runner.py evals/
COPY --chown=appuser:appuser evals/metric_retrieval_gold/answervice_ko_retrieval.v2.json evals/metric_retrieval_gold/
COPY --chown=appuser:appuser evals/node2_qwen35_2b_full3000_huggingface.receipt.json evals/node2_qwen35_2b_full3000_canary.v1.json evals/

ARG ANSWERVICE_SOURCE_REVISION
ARG ANSWERVICE_SOURCE_DIRTY
ARG ANSWERVICE_SOURCE_FINGERPRINT

RUN printf '%s\n' "$ANSWERVICE_SOURCE_REVISION" | grep -Eq '^[0-9a-f]{40}$' \
    && printf '%s\n' "$ANSWERVICE_SOURCE_DIRTY" | grep -Eq '^(true|false)$' \
    && printf '%s\n' "$ANSWERVICE_SOURCE_FINGERPRINT" | grep -Eq '^[0-9a-f]{64}$'

LABEL org.opencontainers.image.revision="${ANSWERVICE_SOURCE_REVISION}" \
    io.answervice.source.dirty="${ANSWERVICE_SOURCE_DIRTY}" \
    io.answervice.source.fingerprint="${ANSWERVICE_SOURCE_FINGERPRINT}"

WORKDIR /workspace/app/backend
USER appuser
EXPOSE 8000

HEALTHCHECK --interval=5s --timeout=5s --start-period=10s --retries=6 \
    CMD python -c "from urllib.request import urlopen; response = urlopen('http://127.0.0.1:8000/health', timeout=1); response.close()"

ENTRYPOINT ["sh", "./entrypoint.sh"]
