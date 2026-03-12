"""PostgreSQL client for auth (users, verification_codes). Uses DATABASE_URL from .env."""

import os
import logging
from contextlib import contextmanager
from typing import Optional
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
PGSSLMODE = os.getenv("PGSSLMODE", "disable")


def _get_engine_url() -> Optional[str]:
    """Return DATABASE_URL with sslmode appended if not present."""
    if not DATABASE_URL:
        return None
    parsed = urlparse(DATABASE_URL)
    query = parse_qs(parsed.query)
    if "sslmode" not in query and PGSSLMODE:
        query["sslmode"] = [PGSSLMODE]
        new_query = urlencode(query, doseq=True)
        parsed = parsed._replace(query=new_query)
    return urlunparse(parsed)


_engine = None
_SessionLocal = None


def get_engine():
    """Create or return SQLAlchemy engine."""
    global _engine
    if _engine is not None:
        return _engine
    url = _get_engine_url()
    if not url:
        raise ValueError("DATABASE_URL is not set")
    _engine = create_engine(
        url,
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )
    return _engine


def get_session_factory():
    """Create or return session factory."""
    global _SessionLocal
    if _SessionLocal is not None:
        return _SessionLocal
    engine = get_engine()
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return _SessionLocal


@contextmanager
def get_db_session():
    """Context manager for database session."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_auth_tables():
    """Create users, verification_codes and digital_twins tables if they do not exist."""
    with get_db_session() as session:
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                phone VARCHAR(20) NOT NULL UNIQUE,
                password VARCHAR(255) NOT NULL,
                username VARCHAR(50),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS verification_codes (
                id SERIAL PRIMARY KEY,
                phone VARCHAR(20) NOT NULL,
                code VARCHAR(10) NOT NULL,
                type VARCHAR(20) NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_verification_codes_phone_type
            ON verification_codes(phone, type)
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS digital_twins (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                agent_name VARCHAR(100) NOT NULL,
                display_name VARCHAR(100),
                expert_name VARCHAR(100),
                visibility VARCHAR(20) NOT NULL DEFAULT 'private',
                exposure VARCHAR(20) NOT NULL DEFAULT 'brief',
                session_id VARCHAR(100),
                source VARCHAR(50) NOT NULL DEFAULT 'profile_twin',
                role_content TEXT,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(user_id, agent_name)
            )
        """))
        session.execute(text("""
            ALTER TABLE digital_twins
            ADD COLUMN IF NOT EXISTS role_content TEXT
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_digital_twins_user_id
            ON digital_twins(user_id)
        """))
    logger.info("Auth tables initialized")
