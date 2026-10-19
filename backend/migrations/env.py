"""
Alembic environment for the backend's SQLAlchemy models.

The database URL comes from the app config (config/settings.py): DATABASE_URL
in production, the development default otherwise. APP_ENV picks the config.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.database import _import_models, db
from config import get_config

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

_import_models()
target_metadata = db.metadata

# configparser treats % as interpolation, so escape it (e.g. in passwords).
config.set_main_option(
    "sqlalchemy.url", get_config().SQLALCHEMY_DATABASE_URI.replace("%", "%%")
)


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of connecting (alembic upgrade --sql)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=get_config().SQLALCHEMY_ENGINE_OPTIONS.get("connect_args", {}),
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
