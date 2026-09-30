"""Which files people may upload, and what a file REALLY is.

The browser's content type and the file name can say anything. After the upload, the
first bytes of the file are checked ("magic numbers"), and the file is refused if they
don't match an allowed type. HTML, SVG and scripts are never allowed: they could run code
in someone's browser.

Products add their types to ALLOWED_TYPES (e.g. audio for a transcription product).
"""

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class FileType:
    """One allowed kind of file."""

    content_type: str
    extensions: tuple[str, ...]
    label: str
    # A check on the first bytes. None = must be plain text (UTF-8, no control bytes).
    magic: tuple[bytes, ...] | None


# Office files (docx, xlsx, pptx) are ZIP archives: they start like any ZIP file.
_ZIP = (b"PK\x03\x04",)

ALLOWED_TYPES: tuple[FileType, ...] = (
    FileType("application/pdf", ("pdf",), "PDF", (b"%PDF-",)),
    FileType("image/png", ("png",), "PNG image", (b"\x89PNG\r\n\x1a\n",)),
    FileType("image/jpeg", ("jpg", "jpeg"), "JPEG image", (b"\xff\xd8\xff",)),
    FileType("image/gif", ("gif",), "GIF image", (b"GIF87a", b"GIF89a")),
    FileType("image/webp", ("webp",), "WebP image", (b"RIFF",)),  # + "WEBP" at byte 8
    FileType("text/plain", ("txt", "md", "log"), "Text", None),
    FileType("text/csv", ("csv",), "CSV", None),
    FileType("application/json", ("json",), "JSON", None),
    FileType(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ("docx",),
        "Word document",
        _ZIP,
    ),
    FileType(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ("xlsx",),
        "Excel sheet",
        _ZIP,
    ),
    FileType(
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ("pptx",),
        "PowerPoint",
        _ZIP,
    ),
)

# How many bytes `detect()` needs.
SNIFF_BYTES = 8192

_BY_EXTENSION = {ext: t for t in ALLOWED_TYPES for ext in t.extensions}


def extension(filename: str) -> str:
    """ "report.PDF" -> "pdf"."""
    _, dot, ext = filename.rpartition(".")
    return ext.lower() if dot else ""


def type_for_name(filename: str) -> FileType | None:
    """The allowed type for this file name, or None."""
    return _BY_EXTENSION.get(extension(filename))


def allowed_extensions() -> list[str]:
    """For error messages and the file picker: ["pdf", "png", ...]."""
    return sorted(_BY_EXTENSION)


def clean_filename(name: str) -> str:
    """A safe display name: no folders, no control characters, at most 255 characters."""
    name = unicodedata.normalize("NFC", name)
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(c for c in name if unicodedata.category(c)[0] != "C")
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    if len(name) > 255:
        base, dot, ext = name.rpartition(".")
        name = (base[: 250 - len(ext)] + dot + ext) if dot and len(ext) <= 10 else name[:255]
    return name


def _looks_like_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        # The sample may end in the middle of a character: ignore an incomplete last one.
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        if exc.start < len(data) - 3:
            return False
    text = data.decode("utf-8", errors="ignore")
    controls = sum(1 for c in text if unicodedata.category(c) == "Cc" and c not in "\t\n\r\f")
    return controls <= len(text) // 100


def matches(file_type: FileType, head: bytes) -> bool:
    """Do the first bytes fit this type?"""
    if file_type.magic is None:
        return _looks_like_text(head)
    if not any(head.startswith(m) for m in file_type.magic):
        return False
    if file_type.content_type == "image/webp":
        return head[8:12] == b"WEBP"
    return True
