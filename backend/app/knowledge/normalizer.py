import html
import re

_SCRIPT_BLOCK = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_HTML_TAG = re.compile(r"<[^>]+>")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_SPACE = re.compile(r"[ \t]+")
_BLANKS = re.compile(r"\n{3,}")


def normalize_content(content: str) -> str:
    sanitized = _SCRIPT_BLOCK.sub("", content)
    sanitized = _HTML_TAG.sub("", sanitized)
    sanitized = html.unescape(sanitized)
    sanitized = _CONTROL.sub("", sanitized)
    sanitized = "\n".join(_SPACE.sub(" ", line).strip() for line in sanitized.splitlines())
    return _BLANKS.sub("\n\n", sanitized).strip()
