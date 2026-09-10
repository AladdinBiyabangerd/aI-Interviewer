"""Release-to-schema compatibility contract."""

EXPECTED_SCHEMA_REVISION = "20260910_0016"

# Stable, application-owned PostgreSQL advisory-lock key for schema releases.
# Changing this value would allow incompatible migration runners to overlap.
SCHEMA_MIGRATION_LOCK_ID = 4_704_809_835_609_924_945
