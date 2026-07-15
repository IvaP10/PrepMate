# ============================================================================
# Alembic env.py — Migration environment for InterAI
# Loads DB connection from config.settings (same source as the app)
# ============================================================================

from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import URL, engine_from_config, pool

# Ensure the project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Local development may keep database values in key.env. Explicit process or
# container environment variables still take precedence because dotenv does
# not override them by default.
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "key.env"))

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Migrations deliberately read only database configuration. Importing the
# application's global Settings object here makes schema deployment depend on
# unrelated runtime checks such as cookie, OpenAI, or payment configuration.
# URL.create also quotes passwords safely instead of interpolating credentials.
database_url = URL.create(
    drivername="postgresql+psycopg2",
    username=os.getenv("PG_USER", "interai"),
    password=os.getenv("PG_PASSWORD") or None,
    host=os.getenv("PG_HOST", "localhost"),
    port=int(os.getenv("PG_PORT", "5432")),
    database=os.getenv("PG_DBNAME", "ai_interviewer"),
)
config.set_main_option(
    "sqlalchemy.url",
    database_url.render_as_string(hide_password=False).replace("%", "%%"),
)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emit SQL to stdout."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=None,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
