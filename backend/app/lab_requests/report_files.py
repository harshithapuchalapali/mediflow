import os
import uuid
from pathlib import Path, PurePosixPath
from typing import Optional

from fastapi import HTTPException, status

# Backend root (…/backend). Every report path is derived from it.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Controlled storage directory, always RELATIVE to the backend root. The value
# persisted in lab_requests.report_file_path is this relative prefix plus a
# server-generated filename, so no absolute machine path ever reaches the DB.
_UPLOAD_ENV = os.getenv("LAB_REPORT_UPLOAD_DIR", "uploads/lab_reports")
UPLOAD_REL = PurePosixPath(_UPLOAD_ENV.replace("\\", "/"))
if UPLOAD_REL.is_absolute():
    raise RuntimeError("LAB_REPORT_UPLOAD_DIR must be a relative path")

# Configurable maximum upload size (bytes). Default 10 MB.
MAX_REPORT_BYTES = int(os.getenv("LAB_REPORT_MAX_SIZE_MB", "10")) * 1024 * 1024

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}

# Signature-first detection: a file is only accepted when its magic bytes
# match one of the allowlisted medical-report types. Filename extensions are a
# secondary cross-check, never the source of truth.
_MAGIC = (
    (b"%PDF-", ".pdf"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
)
_EXT_BY_TYPE = {
    ".pdf": {".pdf"},
    ".png": {".png"},
    ".jpg": {".jpg", ".jpeg"},
}
MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
}


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail
    )


def _upload_root() -> Path:
    return (BASE_DIR / Path(*UPLOAD_REL.parts)).resolve()


def validate_report(data: bytes, original_filename: Optional[str]) -> str:
    """Validate uploaded bytes and return the controlled stored extension.

    Rejects empty files, oversized files, and anything whose content is not a
    PDF/PNG/JPEG. Raises 422 (the project's standard validation error).
    """
    if not data:
        raise _unprocessable("Uploaded file is empty")
    if len(data) > MAX_REPORT_BYTES:
        raise _unprocessable(
            "File is too large (limit %d MB)"
            % (MAX_REPORT_BYTES // (1024 * 1024))
        )
    kind = None
    for magic, ext in _MAGIC:
        if data.startswith(magic):
            kind = ext
            break
    if kind is None:
        raise _unprocessable(
            "Unsupported file type. Allowed types: PDF, PNG, JPG, JPEG"
        )
    if original_filename:
        hint = PurePosixPath(original_filename.replace("\\", "/")).suffix.lower()
        if hint and hint not in _EXT_BY_TYPE[kind]:
            raise _unprocessable("File content does not match its filename extension")
    return kind


def store_report(data: bytes, ext: str) -> str:
    """Persist bytes under a server-generated unique name.

    The client's original filename is never used for storage. Returns the
    controlled RELATIVE path for lab_requests.report_file_path.
    """
    root = _upload_root()
    root.mkdir(parents=True, exist_ok=True)
    filename = "%s%s" % (uuid.uuid4().hex, ext)
    (root / filename).write_bytes(data)
    return str(UPLOAD_REL / filename)


def resolve_report_path(db_relative: Optional[str]) -> Optional[Path]:
    """Map a stored relative path back to a real file, confined to the root.

    Only the basename is used and it is verified to resolve inside the upload
    directory, so a corrupted database value cannot escape the storage root.
    Returns None when the path is empty, unsafe, or the file is missing.
    """
    if not db_relative:
        return None
    rel = PurePosixPath(db_relative.replace("\\", "/"))
    root = _upload_root().resolve()
    candidate = (root / rel.name).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    return candidate


def delete_report(db_relative: Optional[str]) -> None:
    """Delete a stored report if it exists (never outside the upload root)."""
    path = resolve_report_path(db_relative)
    if path is not None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass