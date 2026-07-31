from dataclasses import dataclass


@dataclass(frozen=True)
class ChunkDraft:
    ordinal: int
    section: str | None
    content: str


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
