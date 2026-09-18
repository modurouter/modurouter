import fcntl

import pytest
import pytest_asyncio
from modurouter.config import ROOT, get_settings
from modurouter.models import Base, RuntimeLock, SyncState
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture(scope="session")
def database_lock():
    """Concurrent local test sessions must not reset each other's schema."""
    directory = ROOT / "server/.runtime"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "test-database.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_schema(database_lock):
    settings = get_settings()
    # Test schema is deliberately separate. Never drop the application database.
    if settings.db_name == "modurouter_test":
        raise RuntimeError("The application database must be separate from the test schema")
    url = settings.database_url.set(database="modurouter_test")
    engine = create_async_engine(url, pool_pre_ping=True)
    async with engine.begin() as connection:
        await connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS=0")
        try:
            for table in reversed(Base.metadata.sorted_tables):
                await connection.exec_driver_sql(f"DROP TABLE IF EXISTS `{table.name}`")
        finally:
            await connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS=1")
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, checkfirst=False))
    await engine.dispose()


@pytest_asyncio.fixture
async def database(test_schema):
    url = get_settings().database_url.set(database="modurouter_test")
    engine = create_async_engine(url, pool_pre_ping=True)
    async with engine.begin() as connection:
        await connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS=0")
        try:
            for table in reversed(Base.metadata.sorted_tables):
                await connection.exec_driver_sql(f"DELETE FROM `{table.name}`")
        finally:
            await connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS=1")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory.begin() as db:
        db.add(RuntimeLock(name="admission"))
        db.add(SyncState(provider_code="openrouter"))
    try:
        yield factory
    finally:
        await engine.dispose()
