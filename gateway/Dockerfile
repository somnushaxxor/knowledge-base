FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        git \
        openssh-client \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY gateway/pyproject.toml gateway/README.md /app/gateway/
COPY gateway/src /app/gateway/src

RUN python -m pip install /app/gateway

RUN groupadd --system gateway \
    && useradd --system --gid gateway --home-dir /app gateway \
    && mkdir -p /app/config /data/bundle /data/state \
    && chown -R gateway:gateway /data

USER gateway

VOLUME ["/data"]
EXPOSE 8000

ENTRYPOINT ["knowledge-gateway"]
