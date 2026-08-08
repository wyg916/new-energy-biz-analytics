import mimetypes
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree


class KnowledgeParseError(ValueError):
    code = "KNOWLEDGE_PARSE_ERROR"


@dataclass(frozen=True)
class ParsedDocument:
    content: str
    mime_type: str
    size_bytes: int
    parser_name: str
    parser_version: str
    blocks: tuple["ParsedBlock", ...]


@dataclass(frozen=True)
class ParsedBlock:
    text: str
    page: int | None
    section: str | None
    paragraph: int


ALLOWED_SUFFIXES = {".md", ".txt", ".docx", ".pdf"}
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_EXTRACTED_CHARS = 4 * 1024 * 1024
MAX_PDF_PAGES = 500
PARSER_VERSION = "hybrid-rag-1.0"


def _text_blocks(content: str, *, markdown: bool) -> tuple[ParsedBlock, ...]:
    blocks: list[ParsedBlock] = []
    section: str | None = None
    paragraph = 0
    for raw in re.split(r"\n\s*\n", content.replace("\r\n", "\n")):
        text = raw.strip()
        if not text:
            continue
        paragraph += 1
        first = text.splitlines()[0].strip()
        if markdown and first.startswith("#"):
            section = first.lstrip("#").strip()[:256] or section
        blocks.append(ParsedBlock(text=text, page=None, section=section, paragraph=paragraph))
    return tuple(blocks)


def _parse_docx(path: Path) -> tuple[str, tuple[ParsedBlock, ...]]:
    try:
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > MAX_EXTRACTED_CHARS:
                raise KnowledgeParseError("DOCX extracted XML exceeds the safety limit")
            xml = archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise KnowledgeParseError("DOCX package is invalid or has no document body") from exc
    root = ElementTree.fromstring(xml)
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    blocks: list[ParsedBlock] = []
    section: str | None = None
    page = 1
    paragraph = 0
    extracted_chars = 0
    for node in root.iter(namespace + "p"):
        paragraph += 1
        pieces: list[str] = []
        for child in node.iter():
            if child.tag == namespace + "t" and child.text:
                pieces.append(child.text)
            elif child.tag == namespace + "tab":
                pieces.append("\t")
            elif child.tag == namespace + "br":
                if child.attrib.get(namespace + "type") == "page":
                    page += 1
                else:
                    pieces.append("\n")
        text = "".join(pieces).strip()
        if not text:
            continue
        extracted_chars += len(text)
        if extracted_chars > MAX_EXTRACTED_CHARS:
            raise KnowledgeParseError("DOCX extracted text exceeds the safety limit")
        style = node.find("./" + namespace + "pPr/" + namespace + "pStyle")
        style_value = style.attrib.get(namespace + "val", "") if style is not None else ""
        if style_value.lower().startswith(("heading", "title")):
            section = text[:256]
        blocks.append(ParsedBlock(text=text, page=page, section=section, paragraph=paragraph))
    if not blocks:
        raise KnowledgeParseError("DOCX contains no extractable text")
    return "\n\n".join(item.text for item in blocks), tuple(blocks)


def _parse_pdf(path: Path) -> tuple[str, tuple[ParsedBlock, ...]]:
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError as exc:
        raise KnowledgeParseError("text PDF parsing requires the locked pypdf dependency") from exc
    try:
        reader = PdfReader(str(path), strict=True)
        if reader.is_encrypted:
            raise KnowledgeParseError("encrypted PDF is not accepted")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise KnowledgeParseError("PDF page count exceeds the safety limit")
        blocks: list[ParsedBlock] = []
        paragraph = 0
        extracted_chars = 0
        for page_number, pdf_page in enumerate(reader.pages, start=1):
            text = pdf_page.extract_text() or ""
            extracted_chars += len(text)
            if extracted_chars > MAX_EXTRACTED_CHARS:
                raise KnowledgeParseError("PDF extracted text exceeds the safety limit")
            for raw in re.split(r"\n\s*\n|(?<=\S)\n(?=\S)", text):
                value = raw.strip()
                if not value:
                    continue
                paragraph += 1
                blocks.append(ParsedBlock(value, page_number, None, paragraph))
    except KnowledgeParseError:
        raise
    except Exception as exc:
        raise KnowledgeParseError("PDF is invalid or is not text-extractable") from exc
    if not blocks:
        raise KnowledgeParseError("PDF contains no extractable text; OCR is not enabled")
    return "\n\n".join(item.text for item in blocks), tuple(blocks)


def parse_document(path: Path) -> ParsedDocument:
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise KnowledgeParseError("supported knowledge types are Markdown, TXT, DOCX and text PDF")
    size = path.stat().st_size
    if size <= 0 or size > MAX_DOCUMENT_BYTES:
        raise KnowledgeParseError("document size is outside the P2A limit")
    suffix = path.suffix.lower()
    if suffix == ".docx":
        content, blocks = _parse_docx(path)
        parser_name = "stdlib_docx_xml"
    elif suffix == ".pdf":
        content, blocks = _parse_pdf(path)
        parser_name = "pypdf_text"
    else:
        try:
            content = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            raise KnowledgeParseError("Markdown/TXT document must use UTF-8 encoding") from exc
        blocks = _text_blocks(content, markdown=suffix == ".md")
        parser_name = "builtin_markdown" if suffix == ".md" else "builtin_text"
    if not content.strip() or not blocks:
        raise KnowledgeParseError("document contains no extractable text")
    return ParsedDocument(
        content=content,
        mime_type=mimetypes.guess_type(path.name)[0] or "text/plain",
        size_bytes=size,
        parser_name=parser_name,
        parser_version=PARSER_VERSION,
        blocks=blocks,
    )
