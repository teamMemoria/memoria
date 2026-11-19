# Deployed frontend access (issue #159)

The hosted school demo uses the existing Agent/Manager profile picker. It is
public: anyone who can reach the frontend can choose one of the seeded demo
profiles and perform actions allowed to that profile. Use demo-appropriate data
and keep this mode off for an authenticated deployment.

## Configuration

Set these variables on the **Railway backend service**:

| Variable | Value |
| --- | --- |
| `MEMORIA_APP_ENV` | `production` |
| `MEMORIA_PUBLIC_DEMO` | `true` |
| `MEMORIA_CORS_ORIGINS` | `https://memoria-ftl.netlify.app` |

`MEMORIA_PUBLIC_DEMO` defaults to `false`. When enabled, `X-Dev-User` can name
only a profile ID in `backend/src/backend/data/demo_profiles.toml`. The identity
provider must also find that user's stored organization membership. Agent
ownership, Manager permissions and organization checks still apply. The profile
list exposes only configured seeded profiles. CORS is a browser access rule,
not identity verification.

`MEMORIA_CORS_ORIGINS` defaults to empty. It accepts comma-separated exact
HTTP(S) origins (scheme, host and optional port; no path). Do not use `*`.
Preflight accepts `GET`, `POST`, `PUT`, `Content-Type`, `X-Dev-User` and the
optional `X-Organization` header. Credentialed browser requests are supported.
Only list an additional origin if that frontend deployment should use the API.

Rayaan must set these **frontend build variables** and redeploy the frontend:

| Variable | Value |
| --- | --- |
| `VITE_API_BASE_URL` | The Railway API's public HTTPS base URL, without `/api` |
| `VITE_PUBLIC_DEMO` | `true` |

The frontend fetches `/api/demo/profiles` without an identity, then sends the
chosen profile ID as `X-Dev-User` on workspace and narration requests. JSON
writes also send `Content-Type: application/json`. The current client uses
`credentials: include`, so the backend returns credentialed CORS headers for
the configured origin. Vite embeds these values at build time.

## Hosted verification

1. Record the Railway API URL below and configure the frontend build with it.
2. Check a preflight from that origin to `/api/agent/conversations` with
   `Access-Control-Request-Method: GET` and
   `Access-Control-Request-Headers: x-dev-user`. Check a JSON `POST` preflight
   with `content-type,x-dev-user`. The response must allow the exact origin.
3. Repeat with an unlisted origin; it must receive no
   `Access-Control-Allow-Origin` header.
4. Open Rayaan's deployed frontend, select a seeded Agent, and load that
   Agent's conversations. Select the seeded Manager and load the team queue.
   Verify an unlisted identity gets 401 and an Agent cannot use a Manager route.

| Item | Value |
| --- | --- |
| Frontend origin | `https://memoria-ftl.netlify.app` (confirmed by Rayaan, November 18) |
| Railway API URL | Pending #157 |
| Seeded profiles and conversation handoff | Pending Derek / #158 |
| Hosted browser and preflight checks | Pending deployment |
