"""Storage service — local disk when no AWS credentials, S3 otherwise.

Local mode stores files under  apps/api/uploads/<key>  and is transparent
to callers: the same key string is returned and accepted by all functions.
"""
import mimetypes
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import structlog

from src.config import settings
from src.exceptions import ValidationError

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB

ALLOWED_MIME_TYPES: frozenset[str] = frozenset({
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/heic",
})

_MAGIC: dict[str, tuple[int, bytes]] = {
    "application/pdf": (0, b"%PDF"),
    "image/jpeg":      (0, b"\xff\xd8\xff"),
    "image/png":       (0, b"\x89PNG\r\n\x1a\n"),
    "image/heic":      (4, b"ftyp"),
}

_UNSAFE_FILENAME = re.compile(r"[^\w.\-]")

# Local uploads directory — relative to this file's package root
_LOCAL_ROOT = Path(__file__).resolve().parent.parent / "uploads"


# ---------------------------------------------------------------------------
# Mode detection
# ---------------------------------------------------------------------------

def _use_local() -> bool:
    """Use local disk when AWS credentials are not configured."""
    return not (settings.AWS_ACCESS_KEY and settings.AWS_SECRET_KEY.get_secret_value())


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _sanitise_filename(name: str) -> str:
    basename = os.path.basename(name.replace("\\", "/"))
    safe = _UNSAFE_FILENAME.sub("_", basename)
    if not safe or safe.startswith("."):
        safe = f"file_{safe.lstrip('.')}" or "file"
    return safe[:100]


def validate_upload(file_bytes: bytes, filename: str, declared_mime: str) -> None:
    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise ValidationError(
            f"File size {len(file_bytes) / 1_048_576:.1f} MB exceeds the 20 MB limit",
            error_code="FILE_TOO_LARGE",
        )
    if declared_mime not in ALLOWED_MIME_TYPES:
        raise ValidationError(
            f"File type '{declared_mime}' is not allowed. "
            f"Accepted: {', '.join(sorted(ALLOWED_MIME_TYPES))}",
            error_code="FILE_TYPE_NOT_ALLOWED",
        )
    if any(seq in filename for seq in ("..", "/", "\\")):
        raise ValidationError(
            "Filename contains illegal path characters",
            error_code="FILENAME_INVALID",
        )
    if declared_mime in _MAGIC:
        offset, expected = _MAGIC[declared_mime]
        actual = file_bytes[offset : offset + len(expected)]
        if actual != expected:
            raise ValidationError(
                f"File contents do not match declared type '{declared_mime}'",
                error_code="FILE_CONTENT_MISMATCH",
            )


# ---------------------------------------------------------------------------
# Key builder
# ---------------------------------------------------------------------------

def build_s3_key(doc_type: str, document_id: str, filename: str) -> str:
    now = datetime.now(UTC)
    safe = _sanitise_filename(filename)
    return f"{doc_type}/{now.year}/{now.month:02d}/{document_id}_{safe}"


# ---------------------------------------------------------------------------
# Local disk helpers
# ---------------------------------------------------------------------------

def _local_path(key: str) -> Path:
    # Prevent path traversal
    safe_key = key.replace("\\", "/").lstrip("/")
    path = (_LOCAL_ROOT / safe_key).resolve()
    if not str(path).startswith(str(_LOCAL_ROOT.resolve())):
        raise ValidationError("Invalid storage key", error_code="FILENAME_INVALID")
    return path


async def _local_upload(file_bytes: bytes, key: str) -> None:
    path = _local_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(file_bytes)
    log.info("file saved locally", key=key, size=len(file_bytes))


async def _local_download(key: str) -> bytes:
    path = _local_path(key)
    if not path.exists():
        raise FileNotFoundError(f"Local file not found: {key}")
    return path.read_bytes()


async def _local_delete(key: str) -> None:
    path = _local_path(key)
    if path.exists():
        path.unlink()
        log.info("local file deleted", key=key)


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------

def _boto_session():  # type: ignore[return]
    import aioboto3
    return aioboto3.Session(
        aws_access_key_id=settings.AWS_ACCESS_KEY or None,
        aws_secret_access_key=settings.AWS_SECRET_KEY.get_secret_value() or None,
        region_name=settings.AWS_REGION,
    )


def _client_kwargs() -> dict:
    kwargs: dict = {}
    if settings.S3_ENDPOINT_URL:
        kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL
    return kwargs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def upload_file(
    file_bytes: bytes,
    filename: str,
    content_type: str,
    doc_type: str,
    document_id: str,
    *,
    uploaded_by: str = "",
) -> str:
    """Upload validated bytes; return the storage key."""
    validate_upload(file_bytes, filename, content_type)
    key = build_s3_key(doc_type, document_id, filename)

    if _use_local():
        await _local_upload(file_bytes, key)
        return key

    session = _boto_session()
    async with session.client("s3", **_client_kwargs()) as s3:
        await s3.put_object(
            Bucket=settings.S3_BUCKET,
            Key=key,
            Body=file_bytes,
            ContentType=content_type,
            Metadata={"uploaded_by": uploaded_by, "document_id": document_id, "original_name": filename},
        )
    log.info("file uploaded to S3", key=key, size=len(file_bytes), document_id=document_id)
    return key


async def get_presigned_url(s3_key: str, expiry: int = 3600) -> str:
    """Return a URL to access the stored file."""
    if _use_local():
        # Return a local API download path instead of a presigned URL
        return f"/api/documents/file/{s3_key}"

    session = _boto_session()
    async with session.client("s3", **_client_kwargs()) as s3:
        url: str = await s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.S3_BUCKET, "Key": s3_key},
            ExpiresIn=expiry,
        )
    return url


async def download_file(s3_key: str) -> bytes:
    """Download and return the raw file bytes."""
    if _use_local():
        return await _local_download(s3_key)

    session = _boto_session()
    async with session.client("s3", **_client_kwargs()) as s3:
        response = await s3.get_object(Bucket=settings.S3_BUCKET, Key=s3_key)
        return await response["Body"].read()


async def delete_file(s3_key: str) -> bool:
    """Delete the stored file; returns True on success."""
    try:
        if _use_local():
            await _local_delete(s3_key)
            return True

        session = _boto_session()
        async with session.client("s3", **_client_kwargs()) as s3:
            await s3.delete_object(Bucket=settings.S3_BUCKET, Key=s3_key)
        log.info("S3 object deleted", key=s3_key)
        return True
    except Exception as exc:
        log.error("delete failed", key=s3_key, error=str(exc))
        return False
