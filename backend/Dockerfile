FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /uvx /bin/

WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=0 \
    UV_NO_DEV=1

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini start.sh ./

RUN uv sync --locked --no-dev

ENV UV_NO_SYNC=1
CMD ["./start.sh"]
