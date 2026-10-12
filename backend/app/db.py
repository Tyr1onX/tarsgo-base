import os
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def database_url() -> URL:
    return URL.create(
        "mysql+pymysql",
        username=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        database=os.environ["DB_NAME"],
        query={"charset": "utf8mb4"},
    )


# Keep naive MySQL DATETIME defaults in UTC; admin leave history converts them to Beijing time.
engine = create_engine(
    database_url(),
    pool_pre_ping=True,
    connect_args={"init_command": "SET time_zone = '+00:00'"},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def check_database() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
