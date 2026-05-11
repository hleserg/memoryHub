"""Alembic env.py for the eval schema migrations.

Reads DB URL from EVAL_DB_URL or falls back to ATMAN_DB_URL.
Uses a distinct version_table (alembic_version_eval) so it does not
collide with main migrations.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None  # using raw SQL migrations, not autogenerate

DB_URL = os.environ.get("EVAL_DB_URL") or os.environ.get(
    "ATMAN_DB_URL", "postgresql+psycopg://atman@localhost:5432/atman"
)


def run_migrations_offline() -> None:
    context.configure(
        url=DB_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table="alembic_version_eval",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    config_dict = config.get_section(config.config_ini_section, {})
    config_dict["sqlalchemy.url"] = DB_URL
    connectable = engine_from_config(config_dict, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table="alembic_version_eval",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
