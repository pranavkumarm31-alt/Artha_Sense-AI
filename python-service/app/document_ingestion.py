import hashlib
import io
import re
from urllib.parse import urlparse

from pypdf import PdfReader


MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_EXTRACTED_CHARACTERS = 1_000_000
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 180


def validate_official_source_url(source_url: str) -> None:
    parsed = urlparse(source_url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("Source URL contains an invalid port.") from error
    official_domain = (
        hostname == "rbi.org.in"
        or hostname.endswith(".rbi.org.in")
        or hostname.endswith(".gov.in")
        or hostname.endswith(".nic.in")
    )
    if (
        parsed.scheme != "https"
        or port not in {None, 443}
        or not official_domain
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Source URL must use HTTPS and an official .gov.in, .nic.in or RBI domain.")


def extract_document_text(filename: str, content_type: str, payload: bytes) -> tuple[str, str]:
    if not payload:
        raise ValueError("The uploaded document is empty.")
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise ValueError("Document exceeds the 10 MB upload limit.")
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension == "pdf" and content_type == "application/pdf":
        try:
            reader = PdfReader(io.BytesIO(payload), strict=True)
            if reader.is_encrypted:
                raise ValueError("Encrypted PDFs are not supported.")
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except ValueError:
            raise
        except Exception as error:
            raise ValueError("The PDF could not be read.") from error
        normalized_type = "application/pdf"
    elif extension in {"txt", "text"} and content_type in {"text/plain", "text/markdown"}:
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValueError("Text documents must be UTF-8 encoded.") from error
        normalized_type = "text/plain"
    else:
        raise ValueError("Only PDF and UTF-8 plain-text documents are supported.")

    text = re.sub(r"[ \t]+\n", "\n", text).strip()
    if not text:
        raise ValueError("No extractable text was found in the document.")
    if len(text) > MAX_EXTRACTED_CHARACTERS:
        raise ValueError("Extracted text exceeds the 1,000,000-character limit.")
    return text, normalized_type


def chunk_text(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(start + CHUNK_SIZE, len(cleaned))
        if end < len(cleaned):
            boundary = cleaned.rfind(" ", start, end)
            if boundary > start + CHUNK_SIZE // 2:
                end = boundary
        chunks.append(cleaned[start:end].strip())
        if end == len(cleaned):
            break
        start = max(start + 1, end - CHUNK_OVERLAP)
    return chunks


def document_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
