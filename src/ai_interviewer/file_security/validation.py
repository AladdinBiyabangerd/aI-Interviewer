"""Bounded file signature and safe-container validation before quarantine."""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

PDF_MEDIA_TYPE = "application/pdf"
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TEXT_MEDIA_TYPE = "text/plain"
ALLOWED_MEDIA_TYPES = frozenset({PDF_MEDIA_TYPE, DOCX_MEDIA_TYPE, TEXT_MEDIA_TYPE})


class UploadValidationError(ValueError):
    """File bytes do not satisfy the bounded upload contract."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    content: bytes
    media_type: str
    content_sha256: str

    @property
    def content_length(self) -> int:
        return len(self.content)


def validate_upload(
    content: bytes,
    *,
    declared_media_type: str,
    maximum_bytes: int,
    maximum_archive_entries: int,
    maximum_archive_uncompressed_bytes: int,
) -> ValidatedUpload:
    """Validate actual bytes rather than trusting a filename or request header."""
    normalized_type = declared_media_type.strip().lower()
    if normalized_type not in ALLOWED_MEDIA_TYPES:
        raise UploadValidationError("media_type_not_allowed")
    if not content:
        raise UploadValidationError("empty_file")
    if len(content) > maximum_bytes:
        raise UploadValidationError("file_too_large")

    detected_type = _detect_media_type(
        content,
        maximum_archive_entries=maximum_archive_entries,
        maximum_archive_uncompressed_bytes=maximum_archive_uncompressed_bytes,
    )
    if normalized_type != detected_type:
        raise UploadValidationError("media_type_mismatch")
    return ValidatedUpload(
        content=content,
        media_type=detected_type,
        content_sha256=hashlib.sha256(content).hexdigest(),
    )


def _detect_media_type(
    content: bytes,
    *,
    maximum_archive_entries: int,
    maximum_archive_uncompressed_bytes: int,
) -> str:
    if content.startswith(b"%PDF-"):
        if b"%%EOF" not in content[-1_024:]:
            raise UploadValidationError("invalid_pdf_signature")
        return PDF_MEDIA_TYPE
    if content.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        _validate_docx_archive(
            content,
            maximum_entries=maximum_archive_entries,
            maximum_uncompressed_bytes=maximum_archive_uncompressed_bytes,
        )
        return DOCX_MEDIA_TYPE
    _validate_plain_text(content)
    return TEXT_MEDIA_TYPE


def _validate_docx_archive(
    content: bytes,
    *,
    maximum_entries: int,
    maximum_uncompressed_bytes: int,
) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > maximum_entries:
                raise UploadValidationError("archive_entry_limit")
            names: set[str] = set()
            total_uncompressed = 0
            for entry in entries:
                normalized = entry.filename.replace("\\", "/")
                path = PurePosixPath(normalized)
                if (
                    not normalized
                    or normalized.startswith("/")
                    or ".." in path.parts
                    or normalized in names
                ):
                    raise UploadValidationError("unsafe_archive_path")
                names.add(normalized)
                if entry.flag_bits & 0x1:
                    raise UploadValidationError("encrypted_archive_entry")
                total_uncompressed += entry.file_size
                if total_uncompressed > maximum_uncompressed_bytes:
                    raise UploadValidationError("archive_uncompressed_limit")
                if (
                    entry.file_size > 1_048_576
                    and max(entry.compress_size, 1) * 100 < entry.file_size
                ):
                    raise UploadValidationError("archive_compression_ratio")
                lowered = normalized.lower()
                if lowered.endswith(("vbaproject.bin", ".exe", ".dll", ".js", ".vbs")):
                    raise UploadValidationError("active_archive_content")
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise UploadValidationError("not_a_docx_container")
            bad_entry = archive.testzip()
            if bad_entry is not None:
                raise UploadValidationError("archive_crc_failure")
    except UploadValidationError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise UploadValidationError("invalid_archive") from exc


def _validate_plain_text(content: bytes) -> None:
    if b"\x00" in content:
        raise UploadValidationError("binary_content_not_allowed")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UploadValidationError("text_must_be_utf8") from exc
    disallowed_controls = sum(
        character < " " and character not in {"\t", "\n", "\r"} for character in text
    )
    if disallowed_controls:
        raise UploadValidationError("text_contains_control_characters")
