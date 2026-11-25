# Memoria frontend

React, TypeScript, and Vite. Use Node 22.

## Regular development

Start the backend with the database and migrations described in the [backend guide](../backend/README.md). For a local demo database, run `uv run seed-demo-profiles` from `backend/` and start the API with `MEMORIA_APP_ENV=development`.

From `frontend/`:

```sh
npm ci
MEMORIA_API_TARGET=http://127.0.0.1:8000 npm run dev
```

Choose a profile supplied by the backend. The selected identity controls which conversations, reviews, and knowledge the API returns.

## School demo

Use the demo backend with the imported ABCD conversations. Set `MEMORIA_API_TARGET` and `MEMORIA_SIMULATION_FILE` in `.env.simulation.local`. Point the latter to the 25-call Layer 1 `scorecards.json` export outside `frontend/`.

```sh
npm run demo -- --port 18906 --strictPort
```

The local adapter checks conversation access with the backend before serving archived scores and evidence. Conversation writes are disabled in simulation. The backend still serves profiles and handles knowledge review.

For communication-style narration, follow the [clip generation guide](../ml/NARRATION.md). Use `ml/output/narration/simulation/clips` or set `MEMORIA_SIMULATION_NARRATION_DIR` to a dedicated clip cache. Restart the preview after preparing it.

## Assessment data

The frontend reads stored call assessments through the [API contracts](../backend/docs/api-contracts.md). Assessment screens display recorded results, limits, references, and cited turns. Scoring and evidence validation run in the backend. Keep the archived demo input and narration cache outside the source tree.

## Hosted build

Netlify builds from `frontend/` using `npm run build`, publishes `dist`, and serves `index.html` for client routes. Set `VITE_API_BASE_URL` to the backend origin without a trailing `/api`. Set `VITE_DEMO_LOGIN=true` only for the hosted demo. The backend must explicitly allow the demo identity header, credentials, and the origin.

## Checks

```sh
npm run lint
npm test
npm run build
```

Brand assets, Inter, and license notices are in `public/`. Codicons are distributed under the [CC BY 4.0 license](public/licenses/codicons-LICENSE.txt).
