from __future__ import annotations

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401 - registra todas as tabelas no metadata
from app.core.config import get_settings
from app.db.base import Base

config = context.config
target_metadata = Base.metadata

# Permite migrar o banco de testes: LOGITRACE_ALEMBIC_URL=<url> alembic upgrade head
db_url = os.environ.get("LOGITRACE_ALEMBIC_URL") or get_settings().database_url
config.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))

POSTGIS_TABLES = {"spatial_ref_sys"}


def include_object(obj, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    if type_ == "table" and name in POSTGIS_TABLES:
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, include_object=include_object
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
