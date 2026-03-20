"""Alembic migration environment — imports Base and DB URL from the app's config."""

from alembic import context  # type: ignore[import-not-found]
from sqlalchemy import engine_from_config, pool

# Alembic Config object — provides access to the .ini file values.
config = context.config

# Import all models so Base.metadata is fully populated.
from backend.models import crate, preference_rule, set_plan, track  # noqa: E402, F401
from backend.models.database import Base  # noqa: E402

target_metadata = Base.metadata

# Set the DB URL from the app's config system if not already set programmatically.
# When called via run_migrations(), the URL is pre-set on the Config object.
# When called via the CLI (alembic upgrade head), we fall back to Settings.
if not config.get_main_option("sqlalchemy.url"):
    from backend.config import settings  # noqa: E402

    config.set_main_option("sqlalchemy.url", settings.db_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Configures the context with just a URL (no Engine needed).
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Creates an Engine and associates a connection with the context.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
