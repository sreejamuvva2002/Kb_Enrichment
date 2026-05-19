from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text, UniqueConstraint, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from src import CONFIG_DIR, REPO_ROOT, iso_now, load_yaml


class Base(DeclarativeBase):
    pass


class Url(Base):
    __tablename__ = "urls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    domain: Mapped[str | None] = mapped_column(String(255))
    url_type: Mapped[str | None] = mapped_column(String(50))
    source_id: Mapped[str | None] = mapped_column(String(100))
    company_id: Mapped[str | None] = mapped_column(String(255))
    doc_id: Mapped[str | None] = mapped_column(String(64))
    storage_backend: Mapped[str | None] = mapped_column(String(100))
    bucket_name: Mapped[str | None] = mapped_column(String(255))
    object_key: Mapped[str | None] = mapped_column(Text)
    cloud_uri: Mapped[str | None] = mapped_column(Text)
    upload_status: Mapped[str | None] = mapped_column(String(50), default="Not Enabled")
    uploaded_at: Mapped[str | None] = mapped_column(String(19))
    upload_etag: Mapped[str | None] = mapped_column(String(255))
    upload_version_id: Mapped[str | None] = mapped_column(String(255))
    upload_size_mb: Mapped[float | None] = mapped_column(Float)
    presigned_url_last_created_at: Mapped[str | None] = mapped_column(String(19))
    local_retention_policy: Mapped[str | None] = mapped_column(String(50))
    local_file_exists: Mapped[bool | None] = mapped_column(Boolean, default=False)
    local_deleted_at: Mapped[str | None] = mapped_column(String(19))
    final_url: Mapped[str | None] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    was_redirected: Mapped[bool | None] = mapped_column(Boolean, default=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    source_backend: Mapped[str | None] = mapped_column(String(100))
    first_discovered_at: Mapped[str | None] = mapped_column(String(19), default=iso_now)
    last_seen_at: Mapped[str | None] = mapped_column(String(19), default=iso_now)
    discovered_by_query: Mapped[str | None] = mapped_column(Text)
    query_family: Mapped[str | None] = mapped_column(String(100))
    query_stage: Mapped[int | None] = mapped_column(Integer)
    discovered_for_company: Mapped[str | None] = mapped_column(String(255))
    ddg_title: Mapped[str | None] = mapped_column(Text)
    ddg_snippet: Mapped[str | None] = mapped_column(Text)
    content_type_detected: Mapped[str | None] = mapped_column(String(255))
    file_extension: Mapped[str | None] = mapped_column(String(32))
    content_fingerprint: Mapped[str | None] = mapped_column(String(64))
    duplicate_of_url: Mapped[str | None] = mapped_column(Text)
    is_duplicate: Mapped[bool | None] = mapped_column(Boolean, default=False)
    content_last_modified: Mapped[str | None] = mapped_column(String(255))
    etag: Mapped[str | None] = mapped_column(String(255))
    response_time_ms: Mapped[int | None] = mapped_column(Integer)
    download_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_download_status: Mapped[str | None] = mapped_column(String(50))
    last_download_at: Mapped[str | None] = mapped_column(String(19))
    file_path: Mapped[str | None] = mapped_column(Text)
    file_size_mb: Mapped[float | None] = mapped_column(Float)
    is_extracted: Mapped[bool | None] = mapped_column(Boolean, default=False)
    processing_status: Mapped[str | None] = mapped_column(String(100))
    relevance_score: Mapped[float | None] = mapped_column(Float)
    confidence_score: Mapped[float | None] = mapped_column(Float)
    priority_domain: Mapped[bool | None] = mapped_column(Boolean, default=False)
    source_type: Mapped[str | None] = mapped_column(String(100))
    source_priority: Mapped[int | None] = mapped_column(Integer)
    retrieved_at: Mapped[str | None] = mapped_column(String(19))
    published_date: Mapped[str | None] = mapped_column(String(64))
    blocked: Mapped[bool | None] = mapped_column(Boolean, default=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class UrlCompanyMap(Base):
    __tablename__ = "url_company_map"
    __table_args__ = (UniqueConstraint("url", "company_name", name="uq_url_company_map"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    company_id: Mapped[str | None] = mapped_column(String(255))
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    discovered_by_query: Mapped[str | None] = mapped_column(Text)
    discovered_at: Mapped[str | None] = mapped_column(String(19), default=iso_now)


class QueryConvergence(Base):
    __tablename__ = "query_convergence"
    __table_args__ = (UniqueConstraint("company_name", "query_text", name="uq_query_convergence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    query_family: Mapped[str | None] = mapped_column(String(100))
    query_set_hash: Mapped[str | None] = mapped_column(String(64))
    temporal_variant: Mapped[str | None] = mapped_column(String(32))
    total_runs: Mapped[int] = mapped_column(Integer, default=0)
    last_run_id: Mapped[str | None] = mapped_column(String(255))
    last_run_at: Mapped[str | None] = mapped_column(String(19))
    urls_found_last_run: Mapped[int] = mapped_column(Integer, default=0)
    new_urls_last_run: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_no_new: Mapped[int] = mapped_column(Integer, default=0)
    is_converged: Mapped[bool] = mapped_column(Boolean, default=False)


class QueryPerformance(Base):
    __tablename__ = "query_performance"
    __table_args__ = (UniqueConstraint("company_name", "query_text", name="uq_query_performance"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    query_family: Mapped[str | None] = mapped_column(String(100))
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    total_urls_found: Mapped[int] = mapped_column(Integer, default=0)
    total_new_urls_found: Mapped[int] = mapped_column(Integer, default=0)
    avg_relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    downloaded_success_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    yield_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    is_low_yield: Mapped[bool] = mapped_column(Boolean, default=False)
    last_run_at: Mapped[str | None] = mapped_column(String(19))


class CompanyConvergence(Base):
    __tablename__ = "company_convergence"

    company_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    total_queries: Mapped[int] = mapped_column(Integer, default=0)
    converged_queries: Mapped[int] = mapped_column(Integer, default=0)
    query_set_hash: Mapped[str | None] = mapped_column(String(64))
    all_converged: Mapped[bool] = mapped_column(Boolean, default=False)
    last_updated: Mapped[str | None] = mapped_column(String(19), default=iso_now)


class ContentFingerprint(Base):
    __tablename__ = "content_fingerprints"

    fingerprint: Mapped[str] = mapped_column(String(64), primary_key=True)
    first_url: Mapped[str | None] = mapped_column(Text)
    first_file_path: Mapped[str | None] = mapped_column(Text)
    first_bucket_name: Mapped[str | None] = mapped_column(String(255))
    first_object_key: Mapped[str | None] = mapped_column(Text)
    first_cloud_uri: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[str | None] = mapped_column(String(19), default=iso_now)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)


class RunRecord(Base):
    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[str | None] = mapped_column(String(19))
    completed_at: Mapped[str | None] = mapped_column(String(19))
    total_urls_seen: Mapped[int] = mapped_column(Integer, default=0)
    new_urls_found: Mapped[int] = mapped_column(Integer, default=0)
    already_known: Mapped[int] = mapped_column(Integer, default=0)
    downloaded_ok: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    duplicates_skipped: Mapped[int] = mapped_column(Integer, default=0)
    project_convergence_pct: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str | None] = mapped_column(Text)


class WebDocument(Base):
    __tablename__ = "web_documents"

    source_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    doc_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    final_url: Mapped[str | None] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(String(255))
    query_used: Mapped[str | None] = mapped_column(Text)
    query_family: Mapped[str | None] = mapped_column(String(100))
    query_stage: Mapped[int | None] = mapped_column(Integer)
    source_type: Mapped[str | None] = mapped_column(String(100))
    source_priority: Mapped[int | None] = mapped_column(Integer)
    retrieved_at: Mapped[str | None] = mapped_column(String(19))
    published_date: Mapped[str | None] = mapped_column(String(64))
    content_type: Mapped[str | None] = mapped_column(String(255))
    file_type: Mapped[str | None] = mapped_column(String(32))
    file_size_mb: Mapped[float | None] = mapped_column(Float)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    b2_bucket: Mapped[str | None] = mapped_column(String(255))
    b2_object_key: Mapped[str | None] = mapped_column(Text)
    b2_uri: Mapped[str | None] = mapped_column(Text)
    processing_status: Mapped[str | None] = mapped_column(String(100))
    relevance_score: Mapped[float | None] = mapped_column(Float)
    confidence_score: Mapped[float | None] = mapped_column(Float)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(String(19), default=iso_now)
    updated_at: Mapped[str | None] = mapped_column(String(19), default=iso_now)


class WebDocumentCompanyLink(Base):
    __tablename__ = "web_document_company_links"
    __table_args__ = (UniqueConstraint("source_id", "company_id", name="uq_web_doc_company"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String(100), nullable=False)
    company_id: Mapped[str | None] = mapped_column(String(255))
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    link_type: Mapped[str | None] = mapped_column(String(100), default="discovered_for")
    confidence_score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[str | None] = mapped_column(String(19), default=iso_now)


Index("ix_urls_normalized_url", Url.normalized_url)
Index("ix_urls_company_id", Url.company_id)
Index("ix_urls_doc_id", Url.doc_id)
Index("ix_urls_canonical_url", Url.canonical_url)
Index("ix_urls_query_family_stage", Url.query_family, Url.query_stage)
Index("ix_urls_object_key", Url.object_key)
Index("ix_urls_content_fingerprint", Url.content_fingerprint)
Index("ix_urls_last_download_status", Url.last_download_status)
Index("ix_url_company_map_company_name_url", UrlCompanyMap.company_name, UrlCompanyMap.url)
Index("ix_query_convergence_company_name_is_converged", QueryConvergence.company_name, QueryConvergence.is_converged)
Index("ix_web_documents_content_hash", WebDocument.content_hash)
Index("ix_web_documents_b2_object_key", WebDocument.b2_object_key)
Index("ix_web_doc_company_links_company_id", WebDocumentCompanyLink.company_id)

_ENGINE = None
_SESSION_FACTORY = None


def load_database_config() -> dict:
    return load_yaml(CONFIG_DIR / "database.yaml")


def get_database_backend() -> str:
    config = load_database_config()
    database_url = os.getenv(config["database_url_env"])
    if not database_url:
        return "sqlite"
    lowered = database_url.lower()
    if lowered.startswith("sqlite"):
        return "sqlite"
    return "postgres"


def _resolve_database_url() -> str:
    config = load_database_config()
    env_name = config["database_url_env"]
    database_url = os.getenv(env_name)
    if database_url:
        if database_url.startswith("postgresql://"):
            return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        if database_url.startswith("postgres://"):
            return database_url.replace("postgres://", "postgresql+psycopg://", 1)
        return database_url
    sqlite_path = REPO_ROOT / Path(config["sqlite_fallback_path"])
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{sqlite_path}"


def _create_engine():
    backend = get_database_backend()
    if backend == "sqlite":
        connect_args = {"check_same_thread": False}
    else:
        connect_args = {"connect_timeout": 10}
    return create_engine(_resolve_database_url(), future=True, pool_pre_ping=True, connect_args=connect_args)


def get_engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = _create_engine()
    return _ENGINE


def get_session_factory():
    global _SESSION_FACTORY
    if _SESSION_FACTORY is None:
        _SESSION_FACTORY = sessionmaker(bind=get_engine(), expire_on_commit=False, class_=Session)
    return _SESSION_FACTORY


def get_connection():
    return get_engine().connect()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_schema() -> None:
    engine = get_engine()
    for table in Base.metadata.sorted_tables:
        table.create(bind=engine, checkfirst=True)


def _add_missing_columns() -> None:
    engine = get_engine()
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            existing_columns = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns or column.primary_key:
                    continue
                compiled_type = column.type.compile(dialect=engine.dialect)
                nullable = "" if column.nullable else " NOT NULL"
                connection.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {column.name} {compiled_type}{nullable}"))


def run_migrations() -> None:
    init_schema()
    _add_missing_columns()


def close_connection() -> None:
    global _ENGINE, _SESSION_FACTORY
    if _ENGINE is not None:
        _ENGINE.dispose()
    _ENGINE = None
    _SESSION_FACTORY = None
