from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models.base import Base
import app.models  # noqa: F401

_settings = get_settings()

engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db() -> None:
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_search"))

        conn.commit()
    Base.metadata.create_all(bind=engine)
    _init_incident_bm25_search()


def _init_incident_bm25_search() -> None:
    with engine.connect() as conn:
        conn.execute(
            text("""
                CREATE OR REPLACE FUNCTION public.incident_searchable_text(
                    primary_error_summary text,
                    primary_error_type text,
                    primary_error_message text,
                    error_keywords jsonb,
                    domain_tags jsonb,
                    suspected_cause text,
                    root_cause_summary text,
                    resolution_summary text
                )
                RETURNS text
                LANGUAGE sql
                IMMUTABLE
                PARALLEL SAFE
                AS $$
                    SELECT concat_ws(
                        ' ',
                        primary_error_summary,
                        primary_error_type,
                        primary_error_message,
                        CASE
                            WHEN error_keywords IS NULL THEN NULL
                            WHEN jsonb_typeof(error_keywords) = 'array' THEN (
                                SELECT string_agg(value, ' ')
                                FROM jsonb_array_elements_text(error_keywords) AS value
                            )
                            ELSE error_keywords::text
                        END,
                        CASE
                            WHEN domain_tags IS NULL THEN NULL
                            WHEN jsonb_typeof(domain_tags) = 'array' THEN (
                                SELECT string_agg(value, ' ')
                                FROM jsonb_array_elements_text(domain_tags) AS value
                            )
                            ELSE domain_tags::text
                        END,
                        suspected_cause,
                        root_cause_summary,
                        resolution_summary
                    )
                $$;
            """)
        )
        conn.execute(
            text("""
                CREATE INDEX IF NOT EXISTS incidents_bm25_search_idx
                ON incidents
                USING bm25 (
                    id,
                    project_name,
                    (
                        public.incident_searchable_text(
                            primary_error_summary,
                            primary_error_type,
                            primary_error_message,
                            error_keywords,
                            domain_tags,
                            suspected_cause,
                            root_cause_summary,
                            resolution_summary
                        )::pdb.simple('alias=searchable_text')
                    )
                )
                WITH (key_field='id');
            """)
        )
        conn.commit()


def get_session() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
