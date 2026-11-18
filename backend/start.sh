#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
uv run alembic upgrade head
exec uv run uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-8000}" "$@"
