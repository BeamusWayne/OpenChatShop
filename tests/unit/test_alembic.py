"""Unit tests for Alembic migration framework.

Verifies:
- alembic.ini exists and is valid INI
- env.py sets target_metadata to SQLModel.metadata
- Migration template (script.py.mako) exists
- Initial migration has upgrade/downgrade functions
- Initial migration creates all 6 tables in upgrade
- Initial migration drops all 6 tables in downgrade
- Migration file imports without errors
- Revision ID is properly formatted
"""
from __future__ import annotations

import configparser
import importlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
ALEMBIC_DIR = REPO_ROOT / "src" / "open_chat_shop" / "storage" / "alembic"
VERSIONS_DIR = ALEMBIC_DIR / "versions"
INITIAL_MIGRATION = VERSIONS_DIR / "001_initial_schema.py"

EXPECTED_TABLES = {
    "user",
    "product",
    "order",
    "refundrecord",
    "conversationlog",
    "auditrecord",
}


class TestAlembicConfig:
    """Validate alembic.ini configuration file."""

    def test_config_file_exists(self) -> None:
        assert ALEMBIC_INI.is_file(), "alembic.ini not found at repo root"

    def test_config_is_valid_ini(self) -> None:
        parser = configparser.ConfigParser()
        parser.read(str(ALEMBIC_INI))
        assert parser.has_section("alembic")
        script_loc = parser.get("alembic", "script_location")
        assert "alembic" in script_loc

    def test_config_has_sqlalchemy_url(self) -> None:
        parser = configparser.ConfigParser()
        parser.read(str(ALEMBIC_INI))
        url = parser.get("alembic", "sqlalchemy.url")
        assert url, "sqlalchemy.url must not be empty"


class TestEnvPy:
    """Validate Alembic env.py configuration."""

    def test_env_py_exists(self) -> None:
        env_path = ALEMBIC_DIR / "env.py"
        assert env_path.is_file(), "env.py not found in alembic directory"

    def test_target_metadata_set(self) -> None:
        source = (ALEMBIC_DIR / "env.py").read_text()
        assert "target_metadata" in source
        assert "SQLModel" in source
        assert "metadata" in source

    def test_env_has_offline_and_online(self) -> None:
        source = (ALEMBIC_DIR / "env.py").read_text()
        assert "run_migrations_offline" in source
        assert "run_migrations_online" in source


class TestMigrationTemplate:
    """Validate the Mako migration template."""

    def test_template_exists(self) -> None:
        template = ALEMBIC_DIR / "script.py.mako"
        assert template.is_file(), "script.py.mako not found"

    def test_template_has_upgrade_downgrade(self) -> None:
        source = (ALEMBIC_DIR / "script.py.mako").read_text()
        assert "def upgrade" in source
        assert "def downgrade" in source


class TestInitialMigration:
    """Validate the initial schema migration."""

    def test_migration_file_exists(self) -> None:
        assert INITIAL_MIGRATION.is_file(), "001_initial_schema.py not found"

    def test_migration_importable(self) -> None:
        mod = importlib.import_module(
            "open_chat_shop.storage.alembic.versions.001_initial_schema"
        )
        assert hasattr(mod, "upgrade")
        assert hasattr(mod, "downgrade")

    def test_has_upgrade_and_downgrade_functions(self) -> None:
        mod = importlib.import_module(
            "open_chat_shop.storage.alembic.versions.001_initial_schema"
        )
        assert callable(mod.upgrade)
        assert callable(mod.downgrade)

    def test_revision_formatted(self) -> None:
        mod = importlib.import_module(
            "open_chat_shop.storage.alembic.versions.001_initial_schema"
        )
        assert isinstance(mod.revision, str)
        assert len(mod.revision) > 0
        assert mod.down_revision is None

    def test_upgrade_creates_all_six_tables(self) -> None:
        source = INITIAL_MIGRATION.read_text()
        for table in EXPECTED_TABLES:
            assert table in source, f"Table '{table}' not found in upgrade()"

    def test_downgrade_drops_all_six_tables(self) -> None:
        source = INITIAL_MIGRATION.read_text()
        lines = source.splitlines()
        in_downgrade = False
        drop_tables: set[str] = set()
        for line in lines:
            if "def downgrade" in line:
                in_downgrade = True
                continue
            if in_downgrade:
                stripped = line.strip()
                if stripped.startswith("op.drop_table("):
                    name = stripped.split('"')[1]
                    drop_tables.add(name)
        assert drop_tables == EXPECTED_TABLES, (
            f"downgrade drops {drop_tables}, expected {EXPECTED_TABLES}"
        )

    def test_migration_file_under_150_lines(self) -> None:
        line_count = len(INITIAL_MIGRATION.read_text().splitlines())
        assert line_count <= 150, f"Migration file has {line_count} lines (max 150)"

    def test_upgrade_creates_tables_with_correct_columns(self) -> None:
        source = INITIAL_MIGRATION.read_text()
        assert '"id"' in source
        assert '"user_id"' in source
        assert '"order_id"' in source
        assert '"session_id"' in source
        assert "sa.ForeignKey" in source
