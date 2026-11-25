# Deployment: production database access and backups

The production database is the `pgvector` service on Railway (Postgres with
pgvector). This page covers which database user is used for what, how the
backend service should reference them, and how to back up and restore the
database by hand.

Nothing on this page is a real credential. Real connection strings belong in
Railway variables or in files outside the repo, never in a commit.

## Two connections, two jobs

| Connection | Database user | Used for | Privileges |
| --- | --- | --- | --- |
| Admin | the pgvector service's own user (`postgres`) | Migrations (`uv run alembic upgrade head`), backups, restores, one-off admin work | Owns the schema; full rights |
| App | `memoria_app` | The running backend (FastAPI / Uvicorn) | `CONNECT` on the database, `USAGE` on schema `public`, `SELECT/INSERT/UPDATE/DELETE` on all tables, `USAGE/SELECT` on all sequences |

`memoria_app` cannot create, alter or drop tables and owns nothing. Default
privileges are set so that tables and sequences the admin user (`postgres`)
creates later, for example in a new migration, get the same grants
automatically. If someone creates tables as a different user, those tables
need explicit grants.

### Running migrations

Migrations always run as the admin user. From `backend/`, with the admin URL
in `DATABASE_URL` (in `postgresql+psycopg://` form):

    DATABASE_URL='postgresql+psycopg://postgres:<admin-password>@<host>:<port>/railway' \
      uv run alembic upgrade head

`backend/start.sh` also runs `alembic upgrade head` before it starts Uvicorn,
using whatever `DATABASE_URL` the service has. When the backend runs as
`memoria_app` this is fine while the database is already at head (it only
reads `alembic_version`). If a deploy includes a new migration, the start-up
upgrade fails on permissions and the app does not start. Run the migration as
admin first (by hand as above, or as a Railway pre-deploy command that sets
`DATABASE_URL` to the admin URL just for that command), then deploy.

## Railway variables for the backend service

The backend reads one variable, `DATABASE_URL`, and it must start with
`postgresql+psycopg://` (SQLAlchemy with the psycopg 3 driver). The pgvector
service's `DATABASE_URL_PRIVATE` starts with `postgres://`, so don't paste it
in directly. Build the backend's URL from the same private host, port and
database name, with the psycopg prefix.

Use the private network address (the host inside `DATABASE_URL_PRIVATE`), not
the public proxy. It only works from services inside the Railway project, so
the database isn't reachable from the internet through the app's connection
string.

On the backend service, set:

| Variable | Value |
| --- | --- |
| `MEMORIA_APP_DB_PASSWORD` | the `memoria_app` password (paste it as a sealed variable) |
| `DATABASE_URL` | `postgresql+psycopg://memoria_app:${{MEMORIA_APP_DB_PASSWORD}}@${{pgvector.PGHOST}}:${{pgvector.PGPORT}}/${{pgvector.PGDATABASE}}` |
| `MIGRATION_DATABASE_URL` (optional, only for a pre-deploy migration step) | `postgresql+psycopg://${{pgvector.PGUSER}}:${{pgvector.PGPASSWORD}}@${{pgvector.PGHOST}}:${{pgvector.PGPORT}}/${{pgvector.PGDATABASE}}` |

`${{pgvector.X}}` is a Railway reference to variable `X` on the service named
`pgvector`. Check the pgvector service's Variables tab: the host, port and
database in those references must match what `DATABASE_URL_PRIVATE` points at.
Adjust the variable names if your template uses different ones.

If you use `MIGRATION_DATABASE_URL`, a pre-deploy command could be:

    sh -c 'DATABASE_URL="$MIGRATION_DATABASE_URL" uv run alembic upgrade head'

## Manual backup with pg_dump

These steps use Docker, so you don't need Postgres installed locally. The
client image's major version must be the same as the server's or newer
(`pg_dump` refuses an older client). Check the server version first.

1. Put the admin connection string in an environment variable without
   echoing it. It's the pgvector service's public URL, from the Railway
   dashboard. Paste it at the prompt:

       read -rs PROD_DB_URL && export PROD_DB_URL

2. Check the server's major version:

       docker run --rm -e PROD_DB_URL pgvector/pgvector:pg18 \
         sh -c 'psql "$PROD_DB_URL" -X -A -t -c "show server_version;"'

   If it prints something other than 18.x, use the matching
   `pgvector/pgvector:pgNN` tag in the steps below.

3. Make a private folder outside the repo:

       mkdir -p ~/memoria-backups && chmod 700 ~/memoria-backups

4. Dump in custom format (compressed, and works with `pg_restore`):

       F="memoria-prod-$(date +%Y%m%d-%H%M%S).dump"
       docker run --rm -e PROD_DB_URL -v ~/memoria-backups:/backups \
         pgvector/pgvector:pg18 \
         sh -c "pg_dump \"\$PROD_DB_URL\" --format=custom --no-owner --file=/backups/$F"
       chmod 600 ~/memoria-backups/$F

5. Check the file isn't empty and that its table of contents can be read:

       ls -lh ~/memoria-backups/$F
       docker run --rm -v ~/memoria-backups:/backups pgvector/pgvector:pg18 \
         sh -c "pg_restore --list /backups/$F | grep -c 'TABLE DATA'"

   The count should be about the same as the number of tables in `public`.

The dump contains customer data. Keep it outside the repo, never commit it,
and delete old dumps you no longer need.

## Restore with pg_restore

Always try a restore on a scratch database first. Restoring over production
replaces live data.

### 1. Pick a backup

Use the newest dump that comes from before the problem started:

    ls -lt ~/memoria-backups/

For a Railway scheduled backup, restore it from the pgvector service's
Backups tab in the dashboard instead. The steps below are for dumps made with
`pg_dump`.

### 2. Restore into a local scratch database and check it

    docker network create memoria-restore
    docker run -d --rm --name memoria-restore-db --network memoria-restore \
      -e POSTGRES_PASSWORD=scratch pgvector/pgvector:pg18

    # wait until it accepts connections
    until docker exec memoria-restore-db pg_isready -U postgres; do sleep 1; done

    F=memoria-prod-YYYYMMDD-HHMMSS.dump   # the file you picked
    docker run --rm --network memoria-restore -v ~/memoria-backups:/backups \
      -e PGPASSWORD=scratch pgvector/pgvector:pg18 \
      pg_restore -h memoria-restore-db -U postgres -d postgres \
        --no-owner --no-privileges --exit-on-error /backups/$F

`--no-privileges` skips the dump's `GRANT ... TO memoria_app` statements.
That role doesn't exist in a scratch database, so without the flag
`--exit-on-error` stops at the first grant (`role "memoria_app" does not
exist`).

Then check the restored database:

    docker exec memoria-restore-db psql -U postgres -X -c "select version_num from alembic_version;"
    docker exec memoria-restore-db psql -U postgres -X -c \
      "select extname, extversion from pg_extension where extname = 'vector';"
    docker exec memoria-restore-db psql -U postgres -X -c \
      "select relname, n_live_tup from pg_stat_user_tables order by relname;"

- `alembic_version` should show the same revision as production
  (`uv run alembic current` against production, as admin).
- The `vector` extension should be there.
- Spot-check row counts for the main tables against production (run
  `select count(*) from <table>` on both).

Clean up afterwards:

    docker stop memoria-restore-db && docker network rm memoria-restore

### 3. Restore into production (only if you really mean it)

1. Stop the backend service in Railway so nothing writes while you restore.
2. Take a fresh `pg_dump` of the current state first (see above), so the
   restore can be undone.
3. Restore as admin, dropping and recreating the objects that are in the dump:

       docker run --rm -e PROD_DB_URL -v ~/memoria-backups:/backups \
         pgvector/pgvector:pg18 \
         sh -c "pg_restore -d \"\$PROD_DB_URL\" --clean --if-exists --no-owner --exit-on-error /backups/$F"

4. Grants on recreated tables come from the default privileges, but check
   that `memoria_app` can still read every table:

       docker run --rm -e PROD_DB_URL pgvector/pgvector:pg18 sh -c 'psql "$PROD_DB_URL" -X -c "
         select relname from pg_class
         where relnamespace = '"'"'public'"'"'::regnamespace and relkind = '"'"'r'"'"'
           and not has_table_privilege('"'"'memoria_app'"'"', oid, '"'"'SELECT,INSERT,UPDATE,DELETE'"'"');"'

   It should return no rows. If it lists tables, re-run the grants:
   `GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO memoria_app;`
   and `GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO memoria_app;`.
5. Run the same checks as for the scratch restore, then start the backend.

## Scheduled backups

Scheduled backups are turned on from the Railway dashboard (pgvector service,
Backups tab), where you also choose the schedule and retention. That isn't
in code.

- [ ] Scheduled backups enabled in the Railway dashboard, with schedule and retention chosen
