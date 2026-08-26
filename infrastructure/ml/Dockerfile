FROM python:3.12-slim@sha256:dd29372629eeba2dd003fd9e9d35a5b8236c44727875a0364254b5127af88e65

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY src/ml/room_demand_v3/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY src /app/src

EXPOSE 8000
CMD ["uvicorn", "src.ml.room_demand_timeseries.runtime_api:app", "--host", "0.0.0.0", "--port", "8000"]
