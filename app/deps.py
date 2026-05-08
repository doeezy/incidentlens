from collections.abc import Generator

from sqlalchemy.orm import Session

from app.database import get_session


def db_session_dep() -> Generator[Session, None, None]:
    yield from get_session()
