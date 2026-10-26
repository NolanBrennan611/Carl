# Basic image for Phase 1. Phase 5 hardens this (multi-stage, pinned digests).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=0 \
    UV_LINK_MODE=copy \
    CARL_DATA_DIR=/data

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

RUN useradd --uid 10001 --create-home carl && mkdir /data && chown carl /data
USER 10001
VOLUME /data

ENV PATH="/app/.venv/bin:$PATH"
ENTRYPOINT ["python", "-m", "carl"]
CMD ["run"]
