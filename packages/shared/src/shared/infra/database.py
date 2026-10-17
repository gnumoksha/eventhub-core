import uuid
from datetime import UTC, datetime
from typing import Annotated

import uuid_utils.compat as uuid_compat
from shared.infra.di import Depends
from shared.settings import settings
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel

# A SQLModel engine (underneath it's actually a SQLAlchemy engine) is what holds the connections to the database.
# You would have one single engine object for all your code to connect to the same database.
database_url = settings.DATABASE_URL
async_database_url = make_url(database_url.unicode_string()).set(drivername="postgresql+asyncpg")
engine = create_async_engine(async_database_url, pool_pre_ping=True)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def create_db_and_tables() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)


async def get_session():
    """
    An AsyncSession tracks changes to the data and communicates with the database.

    We will create a FastAPI dependency with yield that will provide a new
    Session for each request. This is what ensures that we use a single session per request.

    expire_on_commit=False keeps loaded attributes available after a commit.
    """
    async with SessionFactory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


class HasUUID4AsPrimaryKey:
    """Mixin class to add a UUID v4 primary key to a SQLModel."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)


class HasUUID7AsPrimaryKey:
    """Mixin class to add a UUID v7 primary key to a SQLModel."""

    id: uuid.UUID = Field(default_factory=uuid_compat.uuid7, primary_key=True)


class HasCreatedAt:
    """Mixin class to add created_at field to a SQLModel."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class HasUpdatedAt:
    """Mixin class to add updated_at field to a SQLModel."""

    updated_at: datetime | None = Field(
        default_factory=lambda: datetime.now(UTC),
        nullable=False,
        sa_column_kwargs={"onupdate": lambda: datetime.now(UTC)},
    )
