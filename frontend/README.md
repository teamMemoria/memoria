# Memoria Frontend

React + TypeScript with Vite.

## Run

```sh
cd frontend
npm ci
npm run dev
```

Open [localhost:5173](http://localhost:5173). Defaults to Agent.
To run as Manager instead:

```sh
VITE_DEV_ROLE=manager npm run dev
```

Development users are not real sign-in.

## Checks

```sh
npm test
npm run lint
npm run build
```

## Deploying

The hosted demo is built by Netlify from `main`, using `netlify.toml` in the
repo root: base directory `frontend`, `npm run build`, publish `dist`, Node 22.
Every path serves `index.html`, so refreshing a page works. Each pull request
gets its own preview link, and merging to `main` redeploys the site.

Set these in the Netlify dashboard (Project configuration → Environment
variables), then trigger a new deploy, because Vite builds them into the site:

| Variable | Value |
|---|---|
| `VITE_API_BASE_URL` | The hosted backend's HTTPS URL, with no trailing `/api` |
| `VITE_DEMO_LOGIN` | `true`: show the demo profiles and send the chosen one as `X-Dev-User` |

With `VITE_DEMO_LOGIN=true`, anyone with the link can pick a demo profile. That
is the agreed mode for the school demo, not real sign-in. It is off in every
other production build. The backend must accept `X-Dev-User` and allow the
site's origin in CORS, including the `X-Dev-User` header and credentials; it
still enforces every Agent, Manager and organization check.

To try a production build locally against a running backend:

```sh
VITE_DEMO_LOGIN=true VITE_API_BASE_URL=http://localhost:8000 npm run build
npm run preview
```

## Folder structure

```text
frontend/
├── public/
│   ├── brand/        # Memoria logos and animation files
│   ├── fonts/        # Inter font and licence
│   └── licenses/     # Icon licence
└── src/
    ├── main.tsx      # Starts the app
    ├── app/          # Startup, routes, and dependency selection
    │   └── layout/   # Sidebar, logo animation, and page layout
    ├── components/   # Shared controls and icons
    ├── lib/          # HTTP client, demo login switch, development data
    ├── types/        # Shared data types
    └── styles/       # Colours, typography, and shared CSS
```

Tests sit beside the code they check.

## Assets and licences

- Memoria branding: `public/brand/`.
- Inter font: `public/fonts/LICENSE.txt`.
- [Microsoft Codicons](https://github.com/microsoft/vscode-codicons/tree/6b53088f5c55bce7107fb579765364f59cd4ad5d), CC BY 4.0: `public/licenses/codicons-LICENSE.txt`.
