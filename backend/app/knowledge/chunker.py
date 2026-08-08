from dataclasses import dataclass

from app.knowledge.parser import ParsedBlock


@dataclass(frozen=True)
class ChunkDraft:
    ordinal: int
    section: str | None
    content: str
    page: int | None = None
    paragraph_start: int | None = None
    paragraph_end: int | None = None


def chunk_document(content: str, *, max_chars: int = 900) -> list[ChunkDraft]:
    section: str | None = None
    chunks: list[ChunkDraft] = []
    buffer: list[str] = []
    buffer_size = 0

    def flush() -> None:
        nonlocal buffer, buffer_size
        text = "\n".join(buffer).strip()
        if text:
            chunks.append(ChunkDraft(len(chunks), section, text))
        buffer = []
        buffer_size = 0

    for paragraph in content.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        first_line = paragraph.splitlines()[0]
        if first_line.startswith("#"):
            flush()
            section = first_line.lstrip("#").strip()[:256] or section
        if len(paragraph) > max_chars:
            flush()
            for offset in range(0, len(paragraph), max_chars):
                part = paragraph[offset : offset + max_chars].strip()
                if part:
                    chunks.append(ChunkDraft(len(chunks), section, part))
            continue
        if buffer and buffer_size + len(paragraph) + 2 > max_chars:
            flush()
        buffer.append(paragraph)
        buffer_size += len(paragraph) + 2
    flush()
    return chunks


def chunk_parsed_blocks(
    blocks: tuple[ParsedBlock, ...],
    *,
    max_chars: int = 900,
) -> list[ChunkDraft]:
    chunks: list[ChunkDraft] = []
    buffer: list[ParsedBlock] = []
    size = 0

    def flush() -> None:
        nonlocal buffer, size
        if not buffer:
            return
        chunks.append(ChunkDraft(
            ordinal=len(chunks),
            section=buffer[-1].section,
            content="\n\n".join(item.text for item in buffer).strip(),
            page=buffer[0].page if len({item.page for item in buffer}) == 1 else None,
            paragraph_start=buffer[0].paragraph,
            paragraph_end=buffer[-1].paragraph,
        ))
        buffer = []
        size = 0

    for block in blocks:
        if not block.text.strip():
            continue
        if buffer and (
            size + len(block.text) + 2 > max_chars
            or block.section != buffer[-1].section
            or block.page != buffer[-1].page
        ):
            flush()
        if len(block.text) > max_chars:
            flush()
            for offset in range(0, len(block.text), max_chars):
                part = block.text[offset:offset + max_chars].strip()
                if part:
                    chunks.append(ChunkDraft(
                        ordinal=len(chunks), section=block.section, content=part,
                        page=block.page, paragraph_start=block.paragraph,
                        paragraph_end=block.paragraph,
                    ))
            continue
        buffer.append(block)
        size += len(block.text) + 2
    flush()
    return chunks
