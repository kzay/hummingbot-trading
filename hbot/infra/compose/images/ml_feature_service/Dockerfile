FROM python:3.12.9-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PYTHONPATH=/workspace/hbot

WORKDIR /workspace/hbot

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

COPY infra/compose/images/ml_feature_service/requirements-ml-feature-service.txt /tmp/requirements-ml-feature-service.txt
RUN python -m pip install --upgrade pip && \
    python -m pip install -r /tmp/requirements-ml-feature-service.txt && \
    python -c "import lightgbm, pandas; print('ml-feature-service deps ok:', lightgbm.__version__, pandas.__version__)"
