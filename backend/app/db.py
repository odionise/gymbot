from contextlib import contextmanager

from fastapi import Depends
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as db:
        yield db


def locked_row(db, model, *conditions):
    """Refresh under a database lock, always including the caller's owner filter.

    SQLite ignores FOR UPDATE. A no-op primary-key update acquires its writer
    lock before reading mutable state, without changing any recorded value.
    PostgreSQL uses a row lock; both locks last until commit/rollback.
    """
    if db.get_bind().dialect.name == "sqlite":
        key = model.__mapper__.primary_key[0]
        db.execute(update(model).where(*conditions).values({key.key: key})
                   .execution_options(synchronize_session=False))
    return db.scalar(select(model).where(*conditions).with_for_update()
                     .execution_options(populate_existing=True))


@contextmanager
def readonly_transaction(db):
    """One consistent, database-enforced read snapshot on a fresh session.

    Rollback here closes a read transaction. No write is attempted and discarded.
    SQLite's connection-local query_only flag is restored before pool return.
    """
    if db.in_transaction() or db.new or db.dirty or db.deleted:
        raise RuntimeError("Preview requires a fresh database session")
    dialect = db.get_bind().dialect.name
    if dialect not in ("sqlite", "postgresql"):
        raise RuntimeError("Read-only preview supports SQLite and PostgreSQL")
    isolation = "REPEATABLE READ" if dialect == "postgresql" else "SERIALIZABLE"
    connection = db.connection(execution_options={"isolation_level": isolation})
    old_query_only = None
    try:
        if dialect == "postgresql":
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        else:
            old_query_only = int(connection.exec_driver_sql("PRAGMA query_only").scalar())
            connection.exec_driver_sql("PRAGMA query_only = ON")
            # SQLite's legacy driver mode does not BEGIN for SELECT. An
            # explicit transaction keeps all preview queries on one snapshot.
            if not connection.connection.driver_connection.in_transaction:
                connection.exec_driver_sql("BEGIN")
        with db.no_autoflush:
            yield db
            if db.new or db.dirty or db.deleted:
                raise RuntimeError("Preview attempted to mutate ORM state")
    finally:
        try:
            if old_query_only is not None and not connection.closed:
                try:
                    connection.exec_driver_sql(f"PRAGMA query_only = {old_query_only}")
                except Exception:
                    connection.invalidate()
                    raise
        finally:
            db.rollback()


def get_preview_db(db=Depends(get_db)):
    with readonly_transaction(db):
        yield db
