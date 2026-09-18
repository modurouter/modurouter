from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, MetaData
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def new_id() -> str:
    return str(uuid4())


timestamp = DateTime().with_variant(DATETIME(fsp=6), "mysql", "mariadb")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    })


engine = create_async_engine(get_settings().database_url, pool_pre_ping=True, pool_recycle=300,
                             hide_parameters=True)
Session = async_sessionmaker(engine, expire_on_commit=False)


async def get_db():
    async with Session() as session:
        yield session
