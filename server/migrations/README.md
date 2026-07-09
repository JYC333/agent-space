# Server Migrations

Do not hand-edit migration SQL for schema changes.

Schema authoring starts in `server/src/db/schema/`. Run `npm run schema:generate`
from `server/` to let Drizzle generate SQL artifacts and sync them into this
directory; `ops/scripts/start.sh` also runs that command automatically before
server image build and database migration. Run `npm run schema:check` to verify
the committed Drizzle snapshot matches the TypeScript schema without touching
the database or rewriting files.

The runtime migration runner only applies the SQL committed here and records
checksums in `public.server_schema_migrations`.
