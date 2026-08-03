FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY app/backend/requirements.txt .
RUN pip install --disable-pip-version-check -r requirements.txt \
    && useradd --create-home --uid 10001 appuser

COPY --chown=appuser:appuser app/backend/ .
COPY --chown=appuser:appuser infrastructure/database/sql/ddl/00_answervice_app_postgresql.sql migrations/sql/00_answervice_app_postgresql.sql
COPY --chown=appuser:appuser infrastructure/database/sql/queries/i2_gold_recognized_room_revenue.sql migrations/sql/i2_gold_recognized_room_revenue.sql
COPY --chown=appuser:appuser config/access-policy.yaml config/access-policy.yaml
COPY --chown=appuser:appuser src/ ./src/

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=5s --timeout=2s --start-period=10s --retries=6 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"

ENTRYPOINT ["sh", "./entrypoint.sh"]
