ARG PYTHON_IMAGE="python:3.12-alpine@sha256:d09d15e60962ca365d1cd544a48773bac9d33f2fb1b00f2aa0deec78ade7dc31"
ARG BUILD_VERSION="0.1.0"
ARG BUILD_REVISION="unknown"
ARG BUILD_CREATED="1970-01-01T00:00:00Z"

FROM ${PYTHON_IMAGE} AS builder

ARG UV_VERSION=0.9.17

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN pip install --no-cache-dir "uv==${UV_VERSION}"

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --frozen --no-dev --no-editable

FROM ${PYTHON_IMAGE} AS runtime

ARG BUILD_VERSION
ARG BUILD_REVISION
ARG BUILD_CREATED

LABEL org.opencontainers.image.title="AI Interviewer Platform API" \
    org.opencontainers.image.description="Production-oriented AI interviewer application runtime" \
    org.opencontainers.image.version="${BUILD_VERSION}" \
    org.opencontainers.image.revision="${BUILD_REVISION}" \
    org.opencontainers.image.created="${BUILD_CREATED}"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:${PATH}" \
    PORT=8000

WORKDIR /app

RUN apk add --no-cache --upgrade \
        "libcrypto3=3.5.8-r0" \
        "libssl3=3.5.8-r0" \
        "libuuid=2.42.3-r1" \
    && addgroup --system --gid 10001 app \
    && adduser --system --disabled-password --no-create-home --uid 10001 --ingroup app app

COPY --from=builder --chown=10001:10001 /app/.venv /app/.venv
COPY --chown=10001:10001 alembic.ini ./alembic.ini
COPY --chown=10001:10001 migrations ./migrations
COPY --chown=10001:10001 scripts/railway-api-entrypoint.sh /app/railway-api-entrypoint.sh
RUN chmod 755 /app/railway-api-entrypoint.sh

USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import os,urllib.request; p=os.environ.get('PORT','8000'); urllib.request.urlopen(f'http://127.0.0.1:{p}/api/v1/health/live', timeout=2)"]

ENTRYPOINT ["/app/railway-api-entrypoint.sh"]
CMD ["ai-interviewer-api"]
