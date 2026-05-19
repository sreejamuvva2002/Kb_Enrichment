from __future__ import annotations

import hashlib
import os
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from botocore.config import Config
try:
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover - lets non-storage modes import before boto3 install
    class ClientError(Exception):
        pass

from src import CONFIG_DIR, iso_now, load_yaml


def load_storage_config() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "storage.yaml")


def _slugify_company(company_name: str | None) -> str:
    base = (company_name or "general").lower().replace(" ", "_")
    cleaned = "".join(ch for ch in base if ch.isalnum() or ch == "_")
    cleaned = cleaned.strip("_") or "general"
    return cleaned[:20]


def _slugify_domain(url: str) -> str:
    domain = urlparse(url).netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    cleaned = domain.replace(".", "_").replace("-", "_")
    cleaned = "".join(ch for ch in cleaned if ch.isalnum() or ch == "_")
    cleaned = cleaned.strip("_") or "unknown"
    return cleaned[:20]


def _slugify_identifier(value: str | None, fallback: str = "unlinked") -> str:
    base = (value or fallback).lower().replace(" ", "_")
    cleaned = "".join(ch for ch in base if ch.isalnum() or ch in {"_", "-"})
    return (cleaned.strip("_-") or fallback)[:64]


def _sanitize_metadata(metadata: dict[str, str] | None) -> dict[str, str]:
    sanitized: dict[str, str] = {}
    for key, value in (metadata or {}).items():
        text = "" if value is None else str(value)
        normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
        sanitized[str(key)] = normalized
    return sanitized


class StorageManager:
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or load_storage_config()
        self._client = None

    def _get_env(self, name_key: str) -> str:
        env_name = self.config[name_key]
        value = os.getenv(env_name)
        if not value:
            raise ValueError(f"Missing required environment variable: {env_name}")
        return value

    def get_storage_client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client(
                "s3",
                endpoint_url=self._get_env("endpoint_url_env"),
                region_name=self._get_env("region_name_env"),
                aws_access_key_id=self._get_env("access_key_env"),
                aws_secret_access_key=self._get_env("secret_key_env"),
                config=Config(connect_timeout=10, read_timeout=30, retries={"max_attempts": 2, "mode": "standard"}),
            )
        return self._client

    def bucket_name(self) -> str:
        return self._get_env("bucket_name_env")

    def build_object_key(
        self,
        doc_id: str,
        company_name: str | None,
        url: str,
        ext: str,
        *,
        company_id: str | None = None,
        content_hash: str | None = None,
    ) -> str:
        pattern = self.config["object_key_pattern"]
        url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
        content_hash12 = (content_hash or url_hash)[:12]
        extension = ext.lstrip(".") or "bin"
        return pattern.format(
            cloud_prefix=self.config["cloud_prefix"].strip("/"),
            file_type=extension,
            doc_id=doc_id,
            company_id=_slugify_identifier(company_id),
            company_slug=_slugify_company(company_name),
            domain_slug=_slugify_domain(url),
            hash8=url_hash,
            content_hash12=content_hash12,
            ext=extension,
        )

    def upload_file(self, local_path: str | Path, object_key: str, metadata: dict[str, str] | None = None) -> dict[str, Any]:
        client = self.get_storage_client()
        path = Path(local_path)
        extra_args = {"Metadata": _sanitize_metadata(metadata)}
        client.upload_file(str(path), self.bucket_name(), object_key, ExtraArgs=extra_args)
        head = client.head_object(Bucket=self.bucket_name(), Key=object_key)
        return {
            "storage_backend": self.config["storage_backend"],
            "bucket_name": self.bucket_name(),
            "object_key": object_key,
            "cloud_uri": f"b2://{self.bucket_name()}/{object_key}",
            "upload_status": "Uploaded",
            "uploaded_at": iso_now(),
            "upload_etag": str(head.get("ETag", "")).strip('"') or None,
            "upload_version_id": head.get("VersionId"),
            "upload_size_mb": round((head.get("ContentLength", 0) or 0) / (1024 * 1024), 4),
            "notes": None,
        }

    def upload_bytes(self, content: bytes, object_key: str, metadata: dict[str, str] | None = None) -> dict[str, Any]:
        client = self.get_storage_client()
        response = client.put_object(
            Bucket=self.bucket_name(),
            Key=object_key,
            Body=content,
            Metadata=_sanitize_metadata(metadata),
        )
        head = client.head_object(Bucket=self.bucket_name(), Key=object_key)
        return {
            "storage_backend": self.config["storage_backend"],
            "bucket_name": self.bucket_name(),
            "object_key": object_key,
            "cloud_uri": f"b2://{self.bucket_name()}/{object_key}",
            "upload_status": "Uploaded",
            "uploaded_at": iso_now(),
            "upload_etag": str(response.get("ETag", "")).strip('"') or None,
            "upload_version_id": response.get("VersionId"),
            "upload_size_mb": round((head.get("ContentLength", 0) or 0) / (1024 * 1024), 4),
            "notes": None,
        }

    def object_exists(self, object_key: str) -> bool:
        client = self.get_storage_client()
        try:
            client.head_object(Bucket=self.bucket_name(), Key=object_key)
            return True
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")
            if error_code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    def get_object_metadata(self, object_key: str) -> dict[str, Any]:
        client = self.get_storage_client()
        response = client.head_object(Bucket=self.bucket_name(), Key=object_key)
        return dict(response)

    def download_object(self, object_key: str, target_path: str | Path) -> Path:
        client = self.get_storage_client()
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        client.download_file(self.bucket_name(), object_key, str(target))
        return target

    def get_presigned_url(self, object_key: str, expires_seconds: int = 3600) -> str:
        client = self.get_storage_client()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket_name(), "Key": object_key},
            ExpiresIn=expires_seconds,
        )

    def verify_uploaded_object(self, object_key: str, expected_size_bytes: int) -> bool:
        if not self.object_exists(object_key):
            return False
        metadata = self.get_object_metadata(object_key)
        return int(metadata.get("ContentLength", 0) or 0) == int(expected_size_bytes)

    def delete_object(self, object_key: str) -> None:
        client = self.get_storage_client()
        client.delete_object(Bucket=self.bucket_name(), Key=object_key)

    def verify_storage_roundtrip(self) -> dict[str, Any]:
        client = self.get_storage_client()
        client.head_bucket(Bucket=self.bucket_name())
        object_key = f"{self.config['cloud_prefix'].strip('/')}/healthcheck/test.txt"
        payload = b"georgia-ev-kb-builder"
        upload_result = self.upload_bytes(payload, object_key, metadata={"purpose": "healthcheck"})
        metadata = self.get_object_metadata(object_key)
        verified = self.verify_uploaded_object(object_key, len(payload))
        self.delete_object(object_key)
        return {"upload_result": upload_result, "metadata": metadata, "verified": verified}


def get_storage_client():
    return StorageManager().get_storage_client()


def build_object_key(
    doc_id: str,
    company_name: str | None,
    url: str,
    ext: str,
    *,
    company_id: str | None = None,
    content_hash: str | None = None,
) -> str:
    return StorageManager().build_object_key(
        doc_id,
        company_name,
        url,
        ext,
        company_id=company_id,
        content_hash=content_hash,
    )


def upload_file(local_path: str | Path, object_key: str, metadata: dict[str, str] | None = None) -> dict[str, Any]:
    return StorageManager().upload_file(local_path, object_key, metadata)


def upload_bytes(content: bytes, object_key: str, metadata: dict[str, str] | None = None) -> dict[str, Any]:
    return StorageManager().upload_bytes(content, object_key, metadata)


def object_exists(object_key: str) -> bool:
    return StorageManager().object_exists(object_key)


def get_object_metadata(object_key: str) -> dict[str, Any]:
    return StorageManager().get_object_metadata(object_key)


def download_object(object_key: str, target_path: str | Path) -> Path:
    return StorageManager().download_object(object_key, target_path)


def get_presigned_url(object_key: str, expires_seconds: int = 3600) -> str:
    return StorageManager().get_presigned_url(object_key, expires_seconds)


def verify_uploaded_object(object_key: str, expected_size_bytes: int) -> bool:
    return StorageManager().verify_uploaded_object(object_key, expected_size_bytes)
