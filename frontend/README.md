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
    ├── lib/          # Development user provider
    ├── types/        # Shared data types
    └── styles/       # Colours, typography, and shared CSS
```

Tests sit beside the code they check.

## Assets and licences

- Memoria branding: `public/brand/`.
- Inter font: `public/fonts/LICENSE.txt`.
- [Microsoft Codicons](https://github.com/microsoft/vscode-codicons/tree/6b53088f5c55bce7107fb579765364f59cd4ad5d), CC BY 4.0: `public/licenses/codicons-LICENSE.txt`.
