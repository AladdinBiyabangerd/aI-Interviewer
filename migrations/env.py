"""Alembic environment for runtime configuration or a release-owned connection."""

import asyncio
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from ai_interviewer.candidate_inputs import (
    document_models,  # noqa: F401
    extraction_models,  # noqa: F401
    intake_models,  # noqa: F401
    source_text_models,  # noqa: F401
)
from ai_interviewer.candidate_inputs import models as candidate_input_models  # noqa: F401
from ai_interviewer.core.config import Settings
from ai_interviewer.file_security import models as file_security_models  # noqa: F401
from ai_interviewer.identity import models as identity_models  # noqa: F401
from ai_interviewer.persistence import models as persistence_models  # noqa: F401
from ai_interviewer.persistence.base import PersistenceBase
from ai_interviewer.persistence.database import database_connect_args
from ai_interviewer.privacy import models as privacy_models  # noqa: F401
from ai_interviewer.profiling import job_models as profiling_job_models  # noqa: F401
from ai_interviewer.profiling import models as profiling_models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = PersistenceBase.metadata


def _settings() -> Settings:
    return Settings()


def run_migrations_offline() -> None:
    settings = _settings()
    context.configure(
        url=settings.database_url.get_secret_value(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    settings = _settings()
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = settings.database_url.get_secret_value()
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=database_connect_args(settings),
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    provided_connection = config.attributes.get("connection")
    if isinstance(provided_connection, Connection):
        do_run_migrations(provided_connection)
        return
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            runner.run(run_async_migrations())
        return
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
