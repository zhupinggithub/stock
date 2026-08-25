# Database migrations

`schema.sql` is the idempotent MySQL 8 baseline used by the application and import commands.
It is intentionally kept beside future Alembic revisions so an existing installation can
bootstrap without migration state. Schema changes after version 1 should be added as Alembic
revisions in `versions/`.
