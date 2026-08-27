# Database migrations

Alembic revisions are the production schema contract. Run them through `uv run alembic`; do not use ORM `create_all()` against application databases.

Production releases are roll-forward by default. A downgrade exists to validate reversibility in an empty disposable database, but any downgrade that drops or rewrites data requires a reviewed backup and restoration plan before use.
