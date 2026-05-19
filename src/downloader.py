from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from src import CONFIG_DIR, RAW_DATA_DIR, iso_now, load_yaml
from src.query_catalog import load_web_query_catalog
from src.searcher import is_blocked
from src.storage import StorageManager, load_storage_config
from src.tracker import Tracker

LOGGER = logging.getLogger(__name__)

CONTENT_TYPE_TO_FOLDER = {
    "text/html": (RAW_DATA_DIR / "html", "html"),
    "application/pdf": (RAW_DATA_DIR / "pdf", "pdf"),
    "application/json": (RAW_DATA_DIR / "json", "json"),
    "text/csv": (RAW_DATA_DIR / "csv", "csv"),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (RAW_DATA_DIR / "xlsx", "xlsx"),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (RAW_DATA_DIR / "docx", "docx"),
}

URL_EXTENSION_TO_CONTENT_TYPE = {
    ".html": "text/html",
    ".htm": "text/html",
    ".pdf": "application/pdf",
    ".json": "application/json",
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def detect_content_type(url: str, headers: dict[str, Any]) -> str:
    raw_value = (
        headers.get("Content-Type")
        or headers.get("content-type")
        or headers.get("__content_type__")
        or ""
    )
    content_type = str(raw_value).split(";")[0].strip().lower()
    if content_type == "application/octet-stream":
        suffix = Path(urlsplit(url).path).suffix.lower()
        return URL_EXTENSION_TO_CONTENT_TYPE.get(suffix, "unknown")
    if content_type in CONTENT_TYPE_TO_FOLDER:
        return content_type
    suffix = Path(urlsplit(url).path).suffix.lower()
    return URL_EXTENSION_TO_CONTENT_TYPE.get(suffix, "unknown")


def get_target_folder(content_type: str) -> Path | None:
    mapping = CONTENT_TYPE_TO_FOLDER.get(content_type)
    return mapping[0] if mapping else None


def compute_content_fingerprint(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def generate_doc_id(tracker: Tracker) -> str:
    return tracker.get_next_doc_id()


def _slugify_company(company_name: str | None) -> str:
    base = (company_name or "general").lower().replace(" ", "_")
    cleaned = "".join(ch for ch in base if ch.isalnum() or ch == "_")
    cleaned = cleaned.strip("_") or "general"
    return cleaned[:20]


def _slugify_domain(url: str) -> str:
    domain = urlsplit(url).netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    cleaned = domain.replace(".", "_").replace("-", "_")
    cleaned = "".join(ch for ch in cleaned if ch.isalnum() or ch == "_")
    cleaned = cleaned.strip("_") or "unknown"
    return cleaned[:20]


def generate_filename(doc_id: str, company: str | None, url: str, ext: str) -> str:
    url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
    return f"{doc_id}_{_slugify_company(company)}_{_slugify_domain(url)}_{url_hash}.{ext.lstrip('.')}"


def download_with_scrapling(url: str) -> tuple[bytes, dict[str, Any], str]:
    from scrapling.fetchers import DynamicFetcher, Fetcher

    start = time.monotonic()
    try:
        response = Fetcher.get(url, timeout=30000, stealthy_headers=True, impersonate="chrome")
        headers = dict(getattr(response, "headers", {}) or {})
        headers["__status__"] = int(getattr(response, "status", 200) or 200)
        headers["__source_backend__"] = "scrapling_fetcher"
        headers["__response_time_ms__"] = int((time.monotonic() - start) * 1000)
        final_url = str(getattr(response, "url", url))
        body = bytes(getattr(response, "body", b"") or b"")
        if body and headers["__status__"] < 400:
            return body, headers, final_url
    except Exception:
        pass
    start = time.monotonic()
    response = DynamicFetcher.fetch(url, timeout=30000, wait=1000, disable_resources=True)
    headers = dict(getattr(response, "headers", {}) or {})
    headers["__status__"] = int(getattr(response, "status", 200) or 200)
    headers["__source_backend__"] = "scrapling_dynamic"
    headers["__response_time_ms__"] = int((time.monotonic() - start) * 1000)
    final_url = str(getattr(response, "url", url))
    body = bytes(getattr(response, "body", b"") or b"")
    return body, headers, final_url


def download_direct(url: str) -> tuple[bytes, dict[str, Any], str, int, int]:
    settings = load_yaml(CONFIG_DIR / "settings.yaml")
    start = time.monotonic()
    with httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(30.0),
        headers={"User-Agent": settings["user_agent"]},
    ) as client:
        response = client.get(url)
    response_time_ms = int((time.monotonic() - start) * 1000)
    return response.content, dict(response.headers), str(response.url), response.status_code, response_time_ms


def _binary_candidate(url: str) -> bool:
    suffix = Path(urlsplit(url).path).suffix.lower()
    return suffix in {".pdf", ".json", ".csv", ".xlsx", ".docx"}


def _downloaded_flag(local_retention_policy: str, file_path: str | None, file_size_mb: float | None, upload_status: str) -> str:
    if local_retention_policy == "keep":
        if file_path and Path(file_path).exists() and (file_size_mb or 0) > 0:
            return "Yes"
        return "No"
    if local_retention_policy == "delete_after_upload" and upload_status == "Upload Verified":
        return "Yes"
    return "No"


class Downloader:
    def __init__(self, tracker: Tracker):
        self.tracker = tracker
        self.settings = load_yaml(CONFIG_DIR / "settings.yaml")
        self.storage_config = load_storage_config()
        self.storage = StorageManager(self.storage_config)

    def _existing_result(self, url: str, company_name: str | None) -> dict[str, Any] | None:
        record = self.tracker.get_url_record(url)
        if not record:
            return None
        local_retention = record.get("local_retention_policy") or self.storage_config["local_retention_policy"]
        file_path = record.get("file_path")
        upload_status = record.get("upload_status") or "Not Enabled"
        if file_path and Path(file_path).exists() and (record.get("file_size_mb") or 0) > 0:
            downloaded = _downloaded_flag(local_retention, file_path, record.get("file_size_mb"), upload_status)
            return {
                "doc_id": record.get("doc_id"),
                "url": url,
                "company_name": company_name,
                "file_type": record.get("file_extension"),
                "file_path": file_path,
                "file_size_mb": record.get("file_size_mb"),
                "downloaded": downloaded,
                "download_status": "Already Exists",
                "content_type": record.get("content_type_detected"),
                "content_fingerprint": record.get("content_fingerprint"),
                "content_last_modified": record.get("content_last_modified"),
                "etag": record.get("etag"),
                "final_url": record.get("final_url"),
                "was_redirected": record.get("was_redirected"),
                "http_status": record.get("http_status"),
                "source_backend": record.get("source_backend"),
                "response_time_ms": record.get("response_time_ms"),
                "notes": record.get("notes"),
                "storage_backend": record.get("storage_backend"),
                "bucket_name": record.get("bucket_name"),
                "object_key": record.get("object_key"),
                "cloud_uri": record.get("cloud_uri"),
                "upload_status": upload_status,
                "uploaded_at": record.get("uploaded_at"),
                "upload_etag": record.get("upload_etag"),
                "upload_version_id": record.get("upload_version_id"),
                "upload_size_mb": record.get("upload_size_mb"),
                "local_retention_policy": local_retention,
                "is_duplicate": record.get("is_duplicate"),
                "duplicate_of_url": record.get("duplicate_of_url"),
                "relevance_score": record.get("relevance_score"),
                "priority_domain": record.get("priority_domain"),
                "ddg_title": record.get("ddg_title"),
                "ddg_snippet": record.get("ddg_snippet"),
                "downloaded_at": iso_now(),
            }
        if local_retention == "delete_after_upload" and upload_status == "Upload Verified":
            return {
                "doc_id": record.get("doc_id"),
                "url": url,
                "company_name": company_name,
                "file_type": record.get("file_extension"),
                "file_path": None,
                "file_size_mb": record.get("file_size_mb"),
                "downloaded": "Yes",
                "download_status": "Already Exists",
                "content_type": record.get("content_type_detected"),
                "content_fingerprint": record.get("content_fingerprint"),
                "content_last_modified": record.get("content_last_modified"),
                "etag": record.get("etag"),
                "final_url": record.get("final_url"),
                "was_redirected": record.get("was_redirected"),
                "http_status": record.get("http_status"),
                "source_backend": record.get("source_backend"),
                "response_time_ms": record.get("response_time_ms"),
                "notes": record.get("notes"),
                "storage_backend": record.get("storage_backend"),
                "bucket_name": record.get("bucket_name"),
                "object_key": record.get("object_key"),
                "cloud_uri": record.get("cloud_uri"),
                "upload_status": upload_status,
                "uploaded_at": record.get("uploaded_at"),
                "upload_etag": record.get("upload_etag"),
                "upload_version_id": record.get("upload_version_id"),
                "upload_size_mb": record.get("upload_size_mb"),
                "local_retention_policy": local_retention,
                "is_duplicate": record.get("is_duplicate"),
                "duplicate_of_url": record.get("duplicate_of_url"),
                "relevance_score": record.get("relevance_score"),
                "priority_domain": record.get("priority_domain"),
                "ddg_title": record.get("ddg_title"),
                "ddg_snippet": record.get("ddg_snippet"),
                "downloaded_at": iso_now(),
            }
        return None

    def download_url(
        self,
        url: str,
        company_name: str | None,
        doc_id: str | None = None,
        company_id: str | None = None,
    ) -> dict[str, Any]:
        if is_blocked(url):
            result = {
                "doc_id": doc_id or generate_doc_id(self.tracker),
                "url": url,
                "company_name": company_name,
                "file_type": None,
                "file_path": None,
                "file_size_mb": None,
                "downloaded": "No",
                "download_status": "Skipped - Blocked Domain",
                "content_type": None,
                "content_fingerprint": None,
                "content_last_modified": None,
                "etag": None,
                "final_url": url,
                "was_redirected": False,
                "http_status": None,
                "source_backend": None,
                "response_time_ms": 0,
                "notes": "Blocked by configured domain blocklist.",
                "storage_backend": self.storage_config["storage_backend"],
                "bucket_name": None,
                "object_key": None,
                "cloud_uri": None,
                "upload_status": "Not Enabled",
                "uploaded_at": None,
                "upload_etag": None,
                "upload_version_id": None,
                "upload_size_mb": None,
                "local_retention_policy": self.storage_config["local_retention_policy"],
                "is_duplicate": False,
                "duplicate_of_url": None,
                "downloaded_at": iso_now(),
            }
            self.tracker.mark_downloaded(
                url,
                result["doc_id"],
                result["download_status"],
                None,
                None,
                None,
                None,
                None,
                None,
                url,
                False,
                None,
                None,
                0,
                self.storage_config["local_retention_policy"],
                local_file_exists=False,
                source_id=result["doc_id"],
                canonical_url=url,
                notes=result["notes"],
                is_duplicate=False,
            )
            return result
        existing = self._existing_result(url, company_name)
        if existing is not None:
            return existing
        record = self.tracker.get_url_record(url) or {}
        effective_company_id = company_id or record.get("company_id")
        assigned_doc_id = doc_id or generate_doc_id(self.tracker)
        local_retention_policy = self.storage_config["local_retention_policy"]
        upload_status = "Not Enabled"
        upload_result: dict[str, Any] | None = None
        content: bytes = b""
        headers: dict[str, Any] = {}
        final_url = url
        http_status: int | None = None
        response_time_ms = 0
        source_backend: str | None = None
        try:
            if _binary_candidate(url):
                content, headers, final_url, http_status, response_time_ms = download_direct(url)
                source_backend = "httpx"
                if http_status >= 400 or detect_content_type(url, headers) == "text/html":
                    content, headers, final_url = download_with_scrapling(url)
                    http_status = int(headers.get("__status__", http_status or 200))
                    response_time_ms = int(headers.get("__response_time_ms__", response_time_ms))
                    source_backend = str(headers.get("__source_backend__", "scrapling_dynamic"))
            else:
                content, headers, final_url = download_with_scrapling(url)
                http_status = int(headers.get("__status__", 200))
                response_time_ms = int(headers.get("__response_time_ms__", 0))
                source_backend = str(headers.get("__source_backend__", "scrapling_dynamic"))
        except httpx.TooManyRedirects:
            return self._failed_result(url, company_name, assigned_doc_id, "Failed - Redirect Loop", 0)
        except httpx.TimeoutException:
            return self._failed_result(url, company_name, assigned_doc_id, "Failed - Timeout", 30000)
        except httpx.ConnectError:
            return self._failed_result(url, company_name, assigned_doc_id, "Failed - Connection Error", 0)
        except Exception as exc:
            LOGGER.warning("Download failed for %s: %s", url, exc)
            return self._failed_result(url, company_name, assigned_doc_id, "Failed - Connection Error", 0, notes=str(exc))

        content_type = detect_content_type(final_url, headers)
        status = "Downloaded"
        notes = None
        if http_status == 403:
            status = "Failed - Blocked (403)"
        elif http_status == 404:
            status = "Failed - Not Found (404)"
        elif content_type == "unknown":
            status = "Failed - Unknown Type"
        elif not content:
            status = "Failed - Empty File"
        elif len(content) > int(self.settings["max_file_size_mb"]) * 1024 * 1024:
            status = "Failed - Too Large"
        elif len(content) < int(load_web_query_catalog().get("minimum_content_bytes", 0)):
            status = "Failed - Low Content"
        if status != "Downloaded":
            return self._failed_result(
                url,
                company_name,
                assigned_doc_id,
                status,
                response_time_ms,
                final_url=final_url,
                http_status=http_status,
                source_backend=source_backend,
                notes=notes,
            )
        if content_type == "text/html" and b"<noscript" in content.lower() and b"enable javascript" in content.lower():
            return self._failed_result(
                url,
                company_name,
                assigned_doc_id,
                "Failed - JS Required",
                response_time_ms,
                final_url=final_url,
                http_status=http_status,
                source_backend=source_backend,
            )

        fingerprint = compute_content_fingerprint(content)
        duplicate_of_url = self.tracker.fingerprint_exists(fingerprint)
        if duplicate_of_url:
            result = {
                "doc_id": assigned_doc_id,
                "url": url,
                "company_name": company_name,
                "file_type": CONTENT_TYPE_TO_FOLDER[content_type][1] if content_type in CONTENT_TYPE_TO_FOLDER else None,
                "file_path": None,
                "file_size_mb": round(len(content) / (1024 * 1024), 4),
                "downloaded": "No",
                "download_status": "Duplicate Content",
                "content_type": content_type,
                "content_fingerprint": fingerprint,
                "content_last_modified": headers.get("Last-Modified") or headers.get("last-modified"),
                "etag": headers.get("ETag") or headers.get("etag"),
                "final_url": final_url,
                "was_redirected": final_url != url,
                "http_status": http_status,
                "source_backend": source_backend,
                "response_time_ms": response_time_ms,
                "notes": None,
                "storage_backend": self.storage_config["storage_backend"],
                "bucket_name": None,
                "object_key": None,
                "cloud_uri": None,
                "upload_status": "Skipped - Duplicate Content",
                "uploaded_at": None,
                "upload_etag": None,
                "upload_version_id": None,
                "upload_size_mb": None,
                "local_retention_policy": local_retention_policy,
                "is_duplicate": True,
                "duplicate_of_url": duplicate_of_url,
                "downloaded_at": iso_now(),
            }
            self.tracker.mark_downloaded(
                url,
                assigned_doc_id,
                result["download_status"],
                None,
                content_type,
                fingerprint,
                result["content_last_modified"],
                result["etag"],
                result["file_size_mb"],
                final_url,
                final_url != url,
                http_status,
                source_backend,
                response_time_ms,
                local_retention_policy,
                local_file_exists=False,
                duplicate_of_url=str(duplicate_of_url),
                source_id=assigned_doc_id,
                canonical_url=final_url,
                is_duplicate=True,
            )
            return result

        folder = get_target_folder(content_type)
        if folder is None:
            return self._failed_result(url, company_name, assigned_doc_id, "Failed - Unknown Type", response_time_ms)
        folder.mkdir(parents=True, exist_ok=True)
        extension = CONTENT_TYPE_TO_FOLDER[content_type][1]
        filename = generate_filename(assigned_doc_id, company_name, url, extension)
        local_path = folder / filename
        local_path.write_bytes(content)
        file_size_mb = round(local_path.stat().st_size / (1024 * 1024), 4)

        if self.storage_config.get("upload_after_download", True):
            try:
                object_key = self.storage.build_object_key(
                    assigned_doc_id,
                    company_name,
                    url,
                    extension,
                    company_id=effective_company_id,
                    content_hash=fingerprint,
                )
                upload_result = self.storage.upload_file(
                    local_path,
                    object_key,
                    metadata={
                        "doc_id": assigned_doc_id,
                        "company_id": effective_company_id or "",
                        "company_name": company_name or "",
                        "source_url": url,
                        "content_hash": fingerprint,
                    },
                )
                if self.storage_config.get("verify_upload", True):
                    verified = self.storage.verify_uploaded_object(object_key, local_path.stat().st_size)
                    upload_result["upload_status"] = "Upload Verified" if verified else "Upload Failed"
                    if not verified:
                        upload_result["notes"] = "Object existence or size verification failed."
                upload_status = upload_result["upload_status"]
            except Exception as exc:
                upload_status = "Upload Failed"
                upload_result = {
                    "storage_backend": self.storage_config["storage_backend"],
                    "bucket_name": None,
                    "object_key": None,
                    "cloud_uri": None,
                    "upload_status": upload_status,
                    "uploaded_at": iso_now(),
                    "upload_etag": None,
                    "upload_version_id": None,
                    "upload_size_mb": None,
                    "notes": str(exc),
                }
        else:
            upload_status = "Not Enabled"
        local_deleted_at = None
        local_file_exists = local_path.exists()
        file_path_for_result = str(local_path)
        if (
            local_retention_policy == "delete_after_upload"
            and upload_result
            and upload_result["upload_status"] == "Upload Verified"
        ):
            local_path.unlink(missing_ok=True)
            local_file_exists = False
            local_deleted_at = iso_now()
            file_path_for_result = None

        self.tracker.mark_downloaded(
            url,
            assigned_doc_id,
            status,
            file_path_for_result,
            content_type,
            fingerprint,
            headers.get("Last-Modified") or headers.get("last-modified"),
            headers.get("ETag") or headers.get("etag"),
            file_size_mb,
            final_url,
            final_url != url,
            http_status,
            source_backend,
            response_time_ms,
            local_retention_policy,
            local_file_exists=local_file_exists,
            local_deleted_at=local_deleted_at,
            source_id=assigned_doc_id,
            canonical_url=final_url,
            is_duplicate=False,
        )
        if upload_result:
            self.tracker.mark_uploaded(url, upload_result)

        result = {
            "doc_id": assigned_doc_id,
            "url": url,
            "company_name": company_name,
            "file_type": extension,
            "file_path": file_path_for_result,
            "file_size_mb": file_size_mb,
            "downloaded": _downloaded_flag(local_retention_policy, file_path_for_result, file_size_mb, upload_status),
            "download_status": status,
            "content_type": content_type,
            "content_fingerprint": fingerprint,
            "content_last_modified": headers.get("Last-Modified") or headers.get("last-modified"),
            "etag": headers.get("ETag") or headers.get("etag"),
            "final_url": final_url,
            "was_redirected": final_url != url,
            "http_status": http_status,
            "source_backend": source_backend,
            "response_time_ms": response_time_ms,
            "notes": upload_result.get("notes") if upload_result else None,
            "storage_backend": self.storage_config["storage_backend"],
            "bucket_name": upload_result.get("bucket_name") if upload_result else None,
            "object_key": upload_result.get("object_key") if upload_result else None,
            "cloud_uri": upload_result.get("cloud_uri") if upload_result else None,
            "upload_status": upload_status,
            "uploaded_at": upload_result.get("uploaded_at") if upload_result else None,
            "upload_etag": upload_result.get("upload_etag") if upload_result else None,
            "upload_version_id": upload_result.get("upload_version_id") if upload_result else None,
            "upload_size_mb": upload_result.get("upload_size_mb") if upload_result else None,
            "local_retention_policy": local_retention_policy,
            "is_duplicate": False,
            "duplicate_of_url": None,
            "downloaded_at": iso_now(),
        }
        return result

    def _failed_result(
        self,
        url: str,
        company_name: str | None,
        doc_id: str,
        status: str,
        response_time_ms: int,
        *,
        final_url: str | None = None,
        http_status: int | None = None,
        source_backend: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        result = {
            "doc_id": doc_id,
            "url": url,
            "company_name": company_name,
            "file_type": None,
            "file_path": None,
            "file_size_mb": None,
            "downloaded": "No",
            "download_status": status,
            "content_type": None,
            "content_fingerprint": None,
            "content_last_modified": None,
            "etag": None,
            "final_url": final_url or url,
            "was_redirected": bool(final_url and final_url != url),
            "http_status": http_status,
            "source_backend": source_backend,
            "response_time_ms": response_time_ms,
            "notes": notes,
            "storage_backend": self.storage_config["storage_backend"],
            "bucket_name": None,
            "object_key": None,
            "cloud_uri": None,
            "upload_status": "Not Enabled",
            "uploaded_at": None,
            "upload_etag": None,
            "upload_version_id": None,
            "upload_size_mb": None,
            "local_retention_policy": self.storage_config["local_retention_policy"],
            "is_duplicate": False,
            "duplicate_of_url": None,
            "downloaded_at": iso_now(),
        }
        self.tracker.mark_downloaded(
            url,
            doc_id,
            status,
            None,
            None,
            None,
            None,
            None,
            None,
            result["final_url"],
            result["was_redirected"],
            http_status,
            source_backend,
            response_time_ms,
            self.storage_config["local_retention_policy"],
            local_file_exists=False,
            source_id=doc_id,
            canonical_url=result["final_url"],
            rejection_reason=status,
            notes=notes,
            is_duplicate=False,
        )
        return result

    def retry_failed(self, tracker: Tracker | None = None) -> dict[str, Any]:
        active_tracker = tracker or self.tracker
        retryable = active_tracker.get_retryable_urls()
        results = []
        for row in retryable:
            results.append(self.download_url(row["url"], row.get("discovered_for_company"), row.get("doc_id")))
            time.sleep(float(self.settings["retry_delay_seconds"]))
        return {"count": len(results), "results": results}
