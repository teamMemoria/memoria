# The backend for local development and demos. Build from the repo root, as
# docker-compose.yml does, because the backend also imports the ml package.
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /usr/local/bin/uv

# Install from uv.lock exactly, and never re-resolve when start.sh runs `uv run`.
ENV UV_FROZEN=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app/backend

# Dependencies first, so editing the code does not reinstall them.
COPY backend/pyproject.toml backend/uv.lock backend/.python-version backend/README.md ./
RUN uv sync --no-install-project

COPY ml /app/ml
COPY backend ./
RUN uv sync

EXPOSE 8000
# Runs the migrations, then the API.
CMD ["sh", "start.sh"]
