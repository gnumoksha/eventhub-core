import uuid
from datetime import UTC, datetime
from typing import Annotated

import uuid_utils.compat as uuid_compat
from shared.infra.di import Depends
from shared.settings import settings
from sqlmodel import Field, Session, SQLModel, create_engine

# A SQLModel engine (underneath it's actually a SQLAlchemy engine) is what holds the connections to the database.
# You would have one single engine object for all your code to connect to the same database.
engine = create_engine(str(settings.DATABASE_URL), pool_pre_ping=True)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def get_session():
    """
    A Session is what stores the objects in memory and keeps track of any
    changes needed in the data, then it uses the engine to communicate with the database.

    We will create a FastAPI dependency with yield that will provide a new
    Session for each request. This is what ensures that we use a single session per request.

    expire_on_commit=False prevents SQLAlchemy from expiring objects after commit(),
    which is necessary because LangChain tools run in ThreadPoolExecutor and need
    to access model attributes after commits happen elsewhere in the request.
    """
    with Session(engine, expire_on_commit=False) as session:
        yield session


def get_static_session() -> Session:
    """
    Workaround to get the session without using the FastAPI dependency injection.
    This is useful inside places where I don't know how to use the get_session().

    expire_on_commit=False prevents SQLAlchemy from expiring objects after commit(),
    which is necessary because LangChain tools run in ThreadPoolExecutor and need
    to access model attributes after commits happen elsewhere in the request.
    """
    return Session(engine, expire_on_commit=False)


SessionDep = Annotated[Session, Depends(get_session)]


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
