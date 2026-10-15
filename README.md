# Memoria

Live agent assist and post-call knowledge learning for support calls.

## Run locally

```bash
cp .env.example .env
docker compose up -d                                   # database
cd backend && uv sync && uv run uvicorn app.main:app --reload   # API on :8000
cd frontend && npm install && npm run dev                       # UI on :5173
```