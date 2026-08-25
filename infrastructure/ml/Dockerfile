FROM python:3.12-slim

WORKDIR /workspace
RUN pip install --disable-pip-version-check \
        numpy==2.2.6 pandas==2.3.3 scikit-learn==1.7.2 \
        skl2onnx==1.19.1 onnx==1.18.0 onnxruntime==1.22.1 joblib==1.5.3 \
        fastapi httpx uvicorn \
    && useradd --create-home --uid 10001 appuser

COPY --chown=appuser:appuser src/ ./src/
ENV PYTHONPATH=/workspace:/workspace/src/ml/reservation_no_show:/workspace/src/ml/room_demand_forecast \
    ML_MODEL_ARTIFACT=/workspace/src/ml/artifacts/live_room_demand.joblib \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=12 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["uvicorn", "--factory", "src.ml.runtime_api:create_app", "--host", "0.0.0.0", "--port", "8000"]
