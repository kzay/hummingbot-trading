FROM python:3.11.9-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PYTHONPATH=/workspace/hbot

WORKDIR /workspace/hbot

COPY compose/images/control_plane/requirements-control-plane.txt /tmp/requirements-control-plane.txt
RUN python -m pip install --upgrade pip && \
    python -m pip install -r /tmp/requirements-control-plane.txt
