# syntax=docker/dockerfile:1.7

# Linux/amd64 manifest digest resolved from Docker Hub on 2026-08-26.
FROM nvidia/cuda:12.9.1-devel-ubuntu24.04@sha256:e542739fcaa4f45da5add8c4cf5769783a61628b2518304a5bbe4ace468b8c8f

SHELL ["/bin/bash", "-euxo", "pipefail", "-c"]

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONNOUSERSITE=1 \
    UV_LINK_MODE=copy \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_DATASETS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    VLLM_NO_USAGE_STATS=1 \
    DO_NOT_TRACK=1 \
    TOKENIZERS_PARALLELISM=false \
    PATH=/opt/node2/venv/bin:/usr/local/cuda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        binutils \
        build-essential \
        ca-certificates \
        libgomp1 \
        libnuma1 \
        python3.12 \
        python3.12-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3.12 -m venv /opt/node2/venv

# uv is installed from one immutable Linux wheel rather than from an index.
ADD --checksum=sha256:8cb1c4af10a1037d2e875ac86da32ea0df20a9623e11769d33515d14158cd3c2 \
    https://files.pythonhosted.org/packages/f6/6b/dbcffa319e640b3f38fc8764b99031773d4449725ca21854309e436c08f9/uv-0.12.6-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl \
    /tmp/uv-0.12.6-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
RUN python -m pip install --no-deps \
        /tmp/uv-0.12.6-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl \
    && rm /tmp/uv-0.12.6-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl \
    && uv --version | grep '^uv 0\.12\.6 '

COPY evals/node2_qwen35_2b_full3000_vllm-cu129.requirements.txt /opt/node2/evals/
COPY evals/node2_qwen35_2b_full3000_vllm-cu129.lock.txt /opt/node2/evals/
COPY evals/node2_qwen35_2b_full3000_serverless-cu129.requirements.txt /opt/node2/evals/
COPY evals/node2_qwen35_2b_full3000_serverless-cu129.lock.txt /opt/node2/evals/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install \
        --python /opt/node2/venv/bin/python \
        --torch-backend=cu129 \
        --require-hashes \
        --no-build \
        --requirement /opt/node2/evals/node2_qwen35_2b_full3000_vllm-cu129.lock.txt \
    && uv pip install \
        --python /opt/node2/venv/bin/python \
        --require-hashes \
        --no-build \
        --requirement /opt/node2/evals/node2_qwen35_2b_full3000_serverless-cu129.lock.txt \
    && python -m pip check

COPY evals/node2_qwen35_2b_full3000_canary.v1.json /opt/node2/evals/
COPY scripts/preflight_node2_vllm.py /opt/node2/scripts/
COPY infrastructure/ai/node2_serverless/handler.py /opt/node2/worker/
COPY infrastructure/ai/node2_serverless/main.py /opt/node2/worker/

# The corrected checkpoint is supplied by RunPod's Hugging Face model cache.
# Runtime network downloads remain disabled; main.py requires a pinned cached
# commit and the startup preflight verifies every checkpoint hash.

WORKDIR /opt/node2/worker
ENTRYPOINT ["/opt/node2/venv/bin/python", "/opt/node2/worker/main.py"]
