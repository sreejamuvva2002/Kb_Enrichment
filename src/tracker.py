from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import func, select

from src import CONFIG_DIR, REPO_ROOT, iso_now, load_yaml
from src.db import (
    CompanyConvergence,
    ContentFingerprint,
    QueryConvergence,
    QueryPerformance,
    RunRecord,
    Url,
    UrlCompanyMap,
    close_connection,
    get_database_backend,
    init_schema,
    load_database_config,
    run_migrations,
    session_scope,
)

LOGGER = logging.getLogger(__name__)
DOMAIN_WIDE_COMPANY = "__DOMAIN__"


def _load_settings() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "settings.yaml")


def _coerce_company_name(company: str | dict[str, Any]) -> str:
    if isinstance(company, dict):
        return str(company["company_name"])
    return str(company)


def _row_to_dict(row: Any, fields: list[str]) -> dict[str, Any]:
    return {field: getattr(row, field) for field in fields}


class Tracker:
    def __init__(self):
        self.database_config = load_database_config()
        self.settings = _load_settings()
        self.database_backend = get_database_backend()
        if self.database_config.get("run_migrations_on_start", True):
            run_migrations()
        else:
            init_schema()

    def init_db(self) -> None:
        init_schema()

    def normalize_url(self, url: str) -> str:
        text = url.strip()
        parts = urlsplit(text)
        scheme = (parts.scheme or "https").lower()
        netloc = parts.netloc.lower()
        if netloc.endswith(":80") and scheme == "http":
            netloc = netloc[:-3]
        if netloc.endswith(":443") and scheme == "https":
            netloc = netloc[:-4]
        path = parts.path or "/"
        query_pairs = sorted(parse_qsl(parts.query, keep_blank_values=True))
        query = urlencode(query_pairs, doseq=True)
        normalized = urlunsplit((scheme, netloc, path.rstrip("/") or "/", query, ""))
        return normalized

    def _get_url_row(self, session, url: str) -> Url | None:
        normalized = self.normalize_url(url)
        return session.scalar(select(Url).where(Url.normalized_url == normalized))

    def get_url_record(self, url: str) -> dict[str, Any] | None:
        with session_scope() as session:
            row = self._get_url_row(session, url)
            if row is None:
                return None
            return _row_to_dict(
                row,
                [
                    "url",
                    "normalized_url",
                    "domain",
                    "url_type",
                    "doc_id",
                    "storage_backend",
                    "bucket_name",
                    "object_key",
                    "cloud_uri",
                    "upload_status",
                    "uploaded_at",
                    "upload_etag",
                    "upload_version_id",
                    "upload_size_mb",
                    "local_retention_policy",
                    "local_file_exists",
                    "local_deleted_at",
                    "final_url",
                    "was_redirected",
                    "http_status",
                    "source_backend",
                    "first_discovered_at",
                    "last_seen_at",
                    "discovered_by_query",
                    "discovered_for_company",
                    "ddg_title",
                    "ddg_snippet",
                    "content_type_detected",
                    "file_extension",
                    "content_fingerprint",
                    "duplicate_of_url",
                    "is_duplicate",
                    "content_last_modified",
                    "etag",
                    "response_time_ms",
                    "download_attempts",
                    "last_download_status",
                    "last_download_at",
                    "file_path",
                    "file_size_mb",
                    "is_extracted",
                    "relevance_score",
                    "priority_domain",
                    "blocked",
                    "notes",
                ],
            )

    def add_url(
        self,
        url: str,
        query: str | None,
        company: str | None,
        ddg_title: str | None,
        ddg_snippet: str | None,
        **extra: Any,
    ) -> bool:
        normalized = self.normalize_url(url)
        with session_scope() as session:
            existing = session.scalar(select(Url).where(Url.normalized_url == normalized))
            now = iso_now()
            if existing is not None:
                existing.last_seen_at = now
                existing.ddg_title = ddg_title or existing.ddg_title
                existing.ddg_snippet = ddg_snippet or existing.ddg_snippet
                existing.discovered_by_query = query or existing.discovered_by_query
                existing.discovered_for_company = company or existing.discovered_for_company
                if extra.get("relevance_score") is not None:
                    existing.relevance_score = float(extra["relevance_score"])
                if extra.get("blocked") is not None:
                    existing.blocked = bool(extra["blocked"])
                if extra.get("priority_domain") is not None:
                    existing.priority_domain = bool(extra["priority_domain"])
                if extra.get("url_type"):
                    existing.url_type = str(extra["url_type"])
                if extra.get("notes"):
                    existing.notes = str(extra["notes"])
                return False
            parts = urlsplit(url)
            row = Url(
                url=url,
                normalized_url=normalized,
                domain=parts.netloc.lower(),
                url_type=extra.get("url_type", "document"),
                upload_status="Not Enabled",
                local_file_exists=False,
                was_redirected=False,
                first_discovered_at=now,
                last_seen_at=now,
                discovered_by_query=query,
                discovered_for_company=company,
                ddg_title=ddg_title,
                ddg_snippet=ddg_snippet,
                source_backend=extra.get("source_backend"),
                relevance_score=float(extra["relevance_score"]) if extra.get("relevance_score") is not None else None,
                priority_domain=bool(extra.get("priority_domain", False)),
                blocked=bool(extra.get("blocked", False)),
                notes=extra.get("notes"),
            )
            session.add(row)
            return True

    def add_url_company_mapping(self, url: str, company: str | None, query: str | None) -> None:
        if not company:
            return
        with session_scope() as session:
            existing = session.scalar(
                select(UrlCompanyMap).where(UrlCompanyMap.url == url, UrlCompanyMap.company_name == company)
            )
            if existing is None:
                session.add(
                    UrlCompanyMap(
                        url=url,
                        company_name=company,
                        discovered_by_query=query,
                        discovered_at=iso_now(),
                    )
                )

    def mark_downloaded(
        self,
        url: str,
        doc_id: str | None,
        status: str,
        file_path: str | None,
        content_type: str | None,
        fingerprint: str | None,
        last_modified: str | None,
        etag: str | None,
        file_size_mb: float | None,
        final_url: str | None,
        was_redirected: bool | None,
        http_status: int | None,
        source_backend: str | None,
        response_time_ms: int | None,
        local_retention_policy: str,
        **extra: Any,
    ) -> None:
        with session_scope() as session:
            row = self._get_url_row(session, url)
            if row is None:
                self.add_url(url, None, None, None, None, url_type=extra.get("url_type", "document"))
                row = self._get_url_row(session, url)
                assert row is not None
            row.doc_id = doc_id or row.doc_id
            row.last_download_status = status
            row.last_download_at = iso_now()
            row.download_attempts = int(row.download_attempts or 0) + 1
            row.file_path = file_path
            row.file_size_mb = file_size_mb
            row.content_type_detected = content_type
            row.content_fingerprint = fingerprint
            row.content_last_modified = last_modified
            row.etag = etag
            row.final_url = final_url
            row.was_redirected = was_redirected
            row.http_status = http_status
            row.source_backend = source_backend
            row.response_time_ms = response_time_ms
            row.local_retention_policy = local_retention_policy
            row.local_deleted_at = extra.get("local_deleted_at")
            row.local_file_exists = bool(extra.get("local_file_exists", False))
            row.duplicate_of_url = extra.get("duplicate_of_url")
            row.is_duplicate = bool(extra.get("is_duplicate", False))
            row.notes = extra.get("notes", row.notes)
            if file_path:
                row.file_extension = Path(file_path).suffix.lstrip(".") or row.file_extension
            elif content_type:
                extension_map = {
                    "text/html": "html",
                    "application/pdf": "pdf",
                    "application/json": "json",
                    "text/csv": "csv",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
                }
                row.file_extension = extension_map.get(content_type, row.file_extension)
            if fingerprint:
                fingerprint_row = session.scalar(
                    select(ContentFingerprint).where(ContentFingerprint.fingerprint == fingerprint)
                )
                if fingerprint_row is None:
                    session.add(
                        ContentFingerprint(
                            fingerprint=fingerprint,
                            first_url=url,
                            first_file_path=file_path,
                            first_bucket_name=extra.get("first_bucket_name"),
                            first_object_key=extra.get("first_object_key"),
                            first_cloud_uri=extra.get("first_cloud_uri"),
                            first_seen_at=iso_now(),
                            duplicate_count=0,
                        )
                    )
                elif fingerprint_row.first_url != url:
                    fingerprint_row.duplicate_count = int(fingerprint_row.duplicate_count or 0) + 1

    def mark_uploaded(self, url: str, upload_result: dict[str, Any]) -> None:
        with session_scope() as session:
            row = self._get_url_row(session, url)
            if row is None:
                return
            row.storage_backend = upload_result.get("storage_backend")
            row.bucket_name = upload_result.get("bucket_name")
            row.object_key = upload_result.get("object_key")
            row.cloud_uri = upload_result.get("cloud_uri")
            row.upload_status = upload_result.get("upload_status")
            row.uploaded_at = upload_result.get("uploaded_at")
            row.upload_etag = upload_result.get("upload_etag")
            row.upload_version_id = upload_result.get("upload_version_id")
            row.upload_size_mb = upload_result.get("upload_size_mb")
            if row.content_fingerprint:
                fingerprint_row = session.scalar(
                    select(ContentFingerprint).where(ContentFingerprint.fingerprint == row.content_fingerprint)
                )
                if fingerprint_row is not None:
                    fingerprint_row.first_bucket_name = fingerprint_row.first_bucket_name or row.bucket_name
                    fingerprint_row.first_object_key = fingerprint_row.first_object_key or row.object_key
                    fingerprint_row.first_cloud_uri = fingerprint_row.first_cloud_uri or row.cloud_uri

    def is_known(self, url: str) -> bool:
        with session_scope() as session:
            return self._get_url_row(session, url) is not None

    def fingerprint_exists(self, fingerprint: str) -> bool | str:
        with session_scope() as session:
            row = session.scalar(select(ContentFingerprint).where(ContentFingerprint.fingerprint == fingerprint))
            if row is None:
                return False
            return row.first_url or False

    def get_retryable_urls(self) -> list[dict[str, Any]]:
        retryable_statuses = {"Failed - Timeout", "Failed - Connection Error", "Failed - JS Required"}
        max_retries = int(self.settings["max_retries"])
        with session_scope() as session:
            rows = session.scalars(
                select(Url).where(
                    Url.last_download_status.in_(retryable_statuses),
                    Url.download_attempts < max_retries,
                )
            ).all()
            return [
                _row_to_dict(
                    row,
                    ["url", "doc_id", "discovered_for_company", "download_attempts", "last_download_status"],
                )
                for row in rows
            ]

    def get_by_doc_id(self, doc_id: str) -> dict[str, Any] | None:
        with session_scope() as session:
            row = session.scalar(select(Url).where(Url.doc_id == doc_id))
            if row is None:
                return None
            return _row_to_dict(row, ["url", "doc_id", "bucket_name", "object_key", "cloud_uri", "file_path"])

    def get_by_object_key(self, object_key: str) -> dict[str, Any] | None:
        with session_scope() as session:
            row = session.scalar(select(Url).where(Url.object_key == object_key))
            if row is None:
                return None
            return _row_to_dict(row, ["url", "doc_id", "bucket_name", "object_key", "cloud_uri", "file_path"])

    def get_cloud_location(self, url: str) -> dict[str, Any] | None:
        with session_scope() as session:
            row = self._get_url_row(session, url)
            if row is None:
                return None
            return _row_to_dict(row, ["bucket_name", "object_key", "cloud_uri", "upload_status"])

    def export_metadata_to_duckdb(self) -> Path:
        import duckdb

        config = load_database_config()
        target_path = REPO_ROOT / Path(config["duckdb_export_path"])
        target_path.parent.mkdir(parents=True, exist_ok=True)
        connection = duckdb.connect(str(target_path))
        try:
            import pandas as pd
            from sqlalchemy import create_engine

            engine = create_engine(self._database_url_for_export())
            for table_name in [
                "urls",
                "url_company_map",
                "query_convergence",
                "query_performance",
                "company_convergence",
                "content_fingerprints",
                "runs",
            ]:
                df = pd.read_sql(f"SELECT * FROM {table_name}", engine)
                connection.register("df_view", df)
                connection.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM df_view")
                connection.unregister("df_view")
        finally:
            connection.close()
        return target_path

    def _database_url_for_export(self) -> str:
        config = load_database_config()
        env_name = config["database_url_env"]
        database_url = os.getenv(env_name)
        if database_url:
            return database_url
        sqlite_path = REPO_ROOT / Path(config["sqlite_fallback_path"])
        return f"sqlite:///{sqlite_path}"

    def update_query_convergence(
        self,
        company: str | dict[str, Any],
        query: str,
        query_family: int,
        temporal_variant: str | None,
        query_set_hash: str,
        new_url_count: int,
        run_id: str,
        urls_found_count: int = 0,
    ) -> None:
        company_name = _coerce_company_name(company)
        target_runs = int(self.settings["query_convergence_consecutive_runs"])
        with session_scope() as session:
            row = session.scalar(
                select(QueryConvergence).where(
                    QueryConvergence.company_name == company_name,
                    QueryConvergence.query_text == query,
                )
            )
            if row is None:
                row = QueryConvergence(
                    company_name=company_name,
                    query_text=query,
                    query_family=query_family,
                    temporal_variant=temporal_variant,
                    query_set_hash=query_set_hash,
                )
                session.add(row)
            elif row.query_set_hash != query_set_hash:
                row.total_runs = 0
                row.consecutive_no_new = 0
                row.is_converged = False
                row.query_set_hash = query_set_hash
            row.query_family = query_family
            row.temporal_variant = temporal_variant
            row.query_set_hash = query_set_hash
            row.total_runs = int(row.total_runs or 0) + 1
            row.last_run_id = run_id
            row.last_run_at = iso_now()
            row.urls_found_last_run = urls_found_count
            row.new_urls_last_run = new_url_count
            row.consecutive_no_new = int(row.consecutive_no_new or 0) + 1 if new_url_count == 0 else 0
            row.is_converged = row.consecutive_no_new >= target_runs
        self._refresh_company_convergence(company_name, query_set_hash)

    def update_query_performance(
        self,
        company: str | dict[str, Any],
        query: str,
        query_family: int,
        urls_found: int,
        new_urls: int,
        avg_relevance: float,
        downloaded_ok: int,
        duplicates: int,
    ) -> None:
        company_name = _coerce_company_name(company)
        low_yield_ratio = float(self.settings["low_yield_ratio_threshold"])
        low_yield_min_runs = int(self.settings["low_yield_min_runs_before_flag"])
        with session_scope() as session:
            row = session.scalar(
                select(QueryPerformance).where(
                    QueryPerformance.company_name == company_name,
                    QueryPerformance.query_text == query,
                )
            )
            if row is None:
                row = QueryPerformance(company_name=company_name, query_text=query, query_family=query_family)
                session.add(row)
            previous_runs = int(row.run_count or 0)
            weighted_relevance = float(row.avg_relevance_score or 0.0) * previous_runs
            row.query_family = query_family
            row.run_count = previous_runs + 1
            row.total_urls_found = int(row.total_urls_found or 0) + urls_found
            row.total_new_urls_found = int(row.total_new_urls_found or 0) + new_urls
            row.downloaded_success_count = int(row.downloaded_success_count or 0) + downloaded_ok
            row.duplicate_count = int(row.duplicate_count or 0) + duplicates
            row.avg_relevance_score = (weighted_relevance + avg_relevance) / row.run_count if row.run_count else 0.0
            row.yield_ratio = (
                row.total_new_urls_found / row.total_urls_found if row.total_urls_found else 0.0
            )
            row.is_low_yield = row.yield_ratio < low_yield_ratio and row.run_count >= low_yield_min_runs
            row.last_run_at = iso_now()
            if row.is_low_yield:
                LOGGER.warning("Low-yield query flagged: %s | %s", company_name, query)

    def is_query_converged(self, company: str | dict[str, Any], query: str) -> bool:
        company_name = _coerce_company_name(company)
        with session_scope() as session:
            row = session.scalar(
                select(QueryConvergence).where(
                    QueryConvergence.company_name == company_name,
                    QueryConvergence.query_text == query,
                )
            )
            return bool(row and row.is_converged)

    def is_company_converged(self, company: str | dict[str, Any]) -> bool:
        company_name = _coerce_company_name(company)
        with session_scope() as session:
            row = session.scalar(select(CompanyConvergence).where(CompanyConvergence.company_name == company_name))
            return bool(row and row.all_converged)

    def get_company_convergence_record(self, company_name: str) -> dict[str, Any] | None:
        with session_scope() as session:
            row = session.scalar(select(CompanyConvergence).where(CompanyConvergence.company_name == company_name))
            if row is None:
                return None
            return _row_to_dict(
                row,
                ["company_name", "total_queries", "converged_queries", "query_set_hash", "all_converged", "last_updated"],
            )

    def is_within_run_gap(self, company: str | dict[str, Any], query: str) -> bool:
        company_name = _coerce_company_name(company)
        with session_scope() as session:
            row = session.scalar(
                select(QueryConvergence).where(
                    QueryConvergence.company_name == company_name,
                    QueryConvergence.query_text == query,
                )
            )
            if row is None or not row.last_run_at:
                return False
            last_run = datetime.strptime(row.last_run_at, "%Y-%m-%d %H:%M:%S")
            days = (
                int(self.settings["minimum_run_gap_converged_days"])
                if row.is_converged
                else int(self.settings["minimum_run_gap_unconverged_days"])
            )
            return datetime.now() < last_run + timedelta(days=days)

    def get_overall_convergence_pct(self) -> float:
        with session_scope() as session:
            total_queries = session.scalar(select(func.count()).select_from(QueryConvergence)) or 0
            if total_queries == 0:
                return 0.0
            converged_queries = session.scalar(
                select(func.count()).select_from(QueryConvergence).where(QueryConvergence.is_converged.is_(True))
            ) or 0
            return round((converged_queries / total_queries) * 100.0, 2)

    def get_convergence_summary(self) -> dict[str, Any]:
        with session_scope() as session:
            rows = session.scalars(
                select(CompanyConvergence)
                .where(CompanyConvergence.company_name != DOMAIN_WIDE_COMPANY)
                .order_by(CompanyConvergence.company_name)
            ).all()
            companies = [
                _row_to_dict(
                    row,
                    ["company_name", "total_queries", "converged_queries", "query_set_hash", "all_converged", "last_updated"],
                )
                for row in rows
            ]
        return {
            "companies": companies,
            "overall_pct": self.get_overall_convergence_pct(),
            "converged_companies": [row["company_name"] for row in companies if row["all_converged"]],
            "unconverged_companies": [row["company_name"] for row in companies if not row["all_converged"]],
            "low_yield_queries": self.get_low_yield_queries(),
        }

    def save_run_summary(self, run_data: dict[str, Any]) -> None:
        with session_scope() as session:
            next_run_number = (session.scalar(select(func.max(RunRecord.run_number))) or 0) + 1
            record = RunRecord(
                run_id=run_data["run_id"],
                run_number=int(run_data.get("run_number") or next_run_number),
                started_at=run_data.get("started_at"),
                completed_at=run_data.get("completed_at"),
                total_urls_seen=int(run_data.get("total_urls_seen", 0)),
                new_urls_found=int(run_data.get("new_urls_found", 0)),
                already_known=int(run_data.get("already_known", 0)),
                downloaded_ok=int(run_data.get("downloaded_ok", 0)),
                failed=int(run_data.get("failed", 0)),
                duplicates_skipped=int(run_data.get("duplicates_skipped", 0)),
                project_convergence_pct=float(run_data.get("project_convergence_pct", 0.0)),
                notes=run_data.get("notes"),
            )
            session.merge(record)

    def compute_query_set_hash(self, query_list: list[Any], temporal_config: dict[str, Any]) -> str:
        normalized_queries = sorted(
            {
                " ".join(
                    (
                        item["query_text"] if isinstance(item, dict) else str(item)
                    ).lower().strip().split()
                )
                for item in query_list
            }
        )
        payload = {"queries": normalized_queries, "temporal_config": temporal_config}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def get_unconverged_queries(
        self, company: str | dict[str, Any], query_bundle: list[dict[str, Any]] | None = None
    ) -> list[dict[str, Any]]:
        company_name = _coerce_company_name(company)
        if query_bundle is None:
            with session_scope() as session:
                rows = session.scalars(
                    select(QueryConvergence).where(QueryConvergence.company_name == company_name)
                ).all()
                return [
                    {"query_text": row.query_text, "family": row.query_family, "temporal_variant": row.temporal_variant}
                    for row in rows
                    if not self.is_within_run_gap(company_name, row.query_text)
                ]
        return [query for query in query_bundle if not self.is_within_run_gap(company_name, query["query_text"])]

    def get_domain_stats(self) -> dict[str, int]:
        with session_scope() as session:
            rows = session.execute(select(Url.domain, func.count()).group_by(Url.domain)).all()
            return {str(domain): int(count) for domain, count in rows if domain}

    def get_low_yield_queries(self) -> list[dict[str, Any]]:
        with session_scope() as session:
            rows = session.scalars(select(QueryPerformance).where(QueryPerformance.is_low_yield.is_(True))).all()
            return [
                _row_to_dict(
                    row,
                    [
                        "company_name",
                        "query_text",
                        "query_family",
                        "run_count",
                        "total_urls_found",
                        "total_new_urls_found",
                        "yield_ratio",
                    ],
                )
                for row in rows
            ]

    def get_next_doc_id(self) -> str:
        with session_scope() as session:
            rows = session.scalars(select(Url.doc_id).where(Url.doc_id.is_not(None))).all()
            highest = 0
            for value in rows:
                if not value:
                    continue
                try:
                    highest = max(highest, int(str(value).split("_")[1]))
                except (IndexError, ValueError):
                    continue
            next_number = highest + 1
            return f"DOC_{next_number:03d}"

    def is_seed_url_within_gap(self, url: str) -> bool:
        with session_scope() as session:
            row = self._get_url_row(session, url)
            if row is None or not row.last_download_at:
                return False
            last_run = datetime.strptime(row.last_download_at, "%Y-%m-%d %H:%M:%S")
            days = int(self.settings["minimum_run_gap_seed_days"])
            return datetime.now() < last_run + timedelta(days=days)

    def count_urls(self) -> int:
        with session_scope() as session:
            return int(session.scalar(select(func.count()).select_from(Url)) or 0)

    def _refresh_company_convergence(self, company_name: str, query_set_hash: str | None) -> None:
        with session_scope() as session:
            rows = session.scalars(
                select(QueryConvergence).where(QueryConvergence.company_name == company_name)
            ).all()
            total = len(rows)
            converged = sum(1 for row in rows if row.is_converged)
            summary = session.scalar(select(CompanyConvergence).where(CompanyConvergence.company_name == company_name))
            if summary is None:
                summary = CompanyConvergence(company_name=company_name)
                session.add(summary)
            summary.total_queries = total
            summary.converged_queries = converged
            summary.query_set_hash = query_set_hash
            summary.all_converged = total > 0 and total == converged
            summary.last_updated = iso_now()

    def close(self) -> None:
        close_connection()


def init_db() -> Tracker:
    return Tracker()
