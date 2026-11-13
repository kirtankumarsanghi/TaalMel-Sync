"""Guard against a schema drift that the in-memory tests cannot see.

The rest of the suite builds tables with SQLModel.metadata.create_all(), which always
matches the models. That means it can never detect a migration that was never written
or never applied. This test runs the real Alembic migrations against a real database
file and then checks that every model column exists in the migrated schema.

If this fails, a model changed without a migration (or the migration chain is broken).
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from sqlmodel import SQLModel

import app.db.models  # noqa: F401  (registers tables on the metadata)

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _alembic_config(db_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", db_url)
    return config


@pytest.fixture
def migrated_db(tmp_path: Path, monkeypatch) -> str:
    db_path = tmp_path / "migrated.db"
    url = f"sqlite:///{db_path.as_posix()}"
    # The migration environment reads the URL from settings.
    monkeypatch.setenv("TAALMEL_DATABASE_URL", url)
    from app.config import get_settings

    get_settings.cache_clear()
    command.upgrade(_alembic_config(url), "head")
    yield url
    get_settings.cache_clear()


def test_migrations_create_every_model_column(migrated_db: str) -> None:
    engine = create_engine(migrated_db)
    inspector = inspect(engine)

    problems: list[str] = []
    for table_name, table in SQLModel.metadata.tables.items():
        if not inspector.has_table(table_name):
            problems.append(f"missing table: {table_name}")
            continue
        actual = {c["name"] for c in inspector.get_columns(table_name)}
        for column in table.columns:
            if column.name not in actual:
                problems.append(f"{table_name}.{column.name} exists in the model but not the database")

    assert not problems, "Model/migration drift:\n" + "\n".join(problems)


def test_migrations_are_reversible(migrated_db: str) -> None:
    """A downgrade to base must succeed, then upgrade again."""
    config = _alembic_config(migrated_db)
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    inspector = inspect(create_engine(migrated_db))
    assert inspector.has_table("events")
    assert inspector.has_table("lab_reports")
    assert inspector.has_table("doctor_questions")
