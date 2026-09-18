"""The already deployed speech revision must retain its identity and data."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

VERSIONS = Path(__file__).resolve().parents[1] / 'backend/migrations/versions'


def apply(connection, name):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        module.upgrade()


def test_single_migration_head_preserves_deployed_speech_revision():
    config = Config()
    config.set_main_option('script_location', str(VERSIONS.parent))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ['0009']
    assert Path(script.get_revision('0006').path).name == '0006_speech_requests.py'
    assert script.get_revision('0007').down_revision == '0006'
    assert script.get_revision('0008').down_revision == '0007'
    assert script.get_revision('0009').down_revision == '0008'


def test_upgrade_from_deployed_speech_schema_preserves_rows():
    engine = sa.create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)')
        connection.exec_driver_sql('CREATE TABLE runs (id VARCHAR(36) PRIMARY KEY)')
        connection.exec_driver_sql("INSERT INTO users VALUES ('existing-user')")
        connection.exec_driver_sql("INSERT INTO runs VALUES ('existing-run')")
        apply(connection, '0006_speech_requests')
        connection.exec_driver_sql("INSERT INTO speech_requests (id,user_id,quota_date,reserved_usd,status,created_at) VALUES ('existing-speech','existing-user','2026-09-18',0.03,'pending','2026-09-18')")
        apply(connection, '0007_routing_choice')
        apply(connection, '0008_runtime_settings')
        connection.exec_driver_sql('CREATE TABLE conversations (id VARCHAR(36) PRIMARY KEY)')
        apply(connection, '0009_learning_sessions')
        assert connection.exec_driver_sql('SELECT id, routing, selected_provider FROM runs').one() == ('existing-run', None, None)
        assert connection.exec_driver_sql('SELECT id, status FROM speech_requests').one() == ('existing-speech', 'pending')
        assert 'runtime_settings' in sa.inspect(connection).get_table_names()
    engine.dispose()
