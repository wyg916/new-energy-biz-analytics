import mimetypes
from dataclasses import dataclass
from pathlib import Path


class KnowledgeParseError(ValueError):
    code = "KNOWLEDGE_PARSE_ERROR"


@dataclass(frozen=True)
class ParsedDocument:
    content: str
    mime_type: str
    size_bytes: int


ALLOWED_SUFFIXES = {".md", ".txt"}
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024


def parse_document(path: Path) -> ParsedDocument:
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise KnowledgeParseError("only tracked Markdown and text files are supported in P2A")
    size = path.stat().st_size
    if size <= 0 or size > MAX_DOCUMENT_BYTES:
        raise KnowledgeParseError("document size is outside the P2A limit")
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise KnowledgeParseError("document must use UTF-8 encoding") from exc
    return ParsedDocument(
        content=content,
        mime_type=mimetypes.guess_type(path.name)[0] or "text/plain",
        size_bytes=size,
    )
