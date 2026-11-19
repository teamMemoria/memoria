FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /uvx /bin/

WORKDIR /app/backend
ENV UV_PYTHON_DOWNLOADS=0 \
    UV_NO_DEV=1 \
    PYTHONPATH=/app

COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
COPY backend/src ./src
COPY backend/alembic ./alembic
COPY backend/alembic.ini backend/start.sh ./
COPY ml /app/ml

RUN uv sync --locked --no-dev

ENV UV_NO_SYNC=1
CMD ["./start.sh"]
