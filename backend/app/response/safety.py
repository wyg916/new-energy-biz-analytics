import re

from app.response.profiles import ResponseProfile

_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)


def sanitize_output_text(value: str) -> str:
    value = _SCRIPT.sub("", value)
    value = _TAG.sub("", value)
    return value.strip()


def enforce_truthfulness(value: str, profile: ResponseProfile) -> str:
    safe = sanitize_output_text(value)
    replacements = {
        "必然导致": "可能相关",
        "确认因果": "观察到相关性",
    }
    for source, target in replacements.items():
        safe = safe.replace(source, target)
    for expression in profile.forbidden_expressions:
        if expression in safe:
            raise ValueError("response contains a forbidden unsupported expression")
    return safe


def clamp_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max(0, max_chars - 1)].rstrip() + "…"
