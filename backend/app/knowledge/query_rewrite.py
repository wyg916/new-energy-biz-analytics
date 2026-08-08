from __future__ import annotations

import re
from dataclasses import dataclass

from app.knowledge.security import prompt_injection_detected

_SPACE = re.compile(r"\s+")
_SYNONYMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("口径", ("定义", "计算规则")),
    ("权限", ("RBAC", "ACL", "授权")),
    ("全文检索", ("FTS", "BM25", "关键词")),
    ("混合检索", ("hybrid", "向量", "关键词", "RRF")),
    ("废止", ("撤回", "retire")),
    ("回滚", ("rollback", "恢复版本")),
    ("来源", ("citation", "引用", "证据")),
)


@dataclass(frozen=True)
class QueryRewrite:
    original: str
    rewritten: str
    expansions: tuple[str, ...]
    rejected: bool
    reason: str | None = None


def rewrite_query(query: str) -> QueryRewrite:
    original = _SPACE.sub(" ", query.strip())
    if prompt_injection_detected(original):
        return QueryRewrite(original, "", (), True, "PROMPT_INJECTION_QUERY")
    expansions: list[str] = []
    lowered = original.lower()
    for trigger, values in _SYNONYMS:
        if trigger.lower() in lowered:
            expansions.extend(value for value in values if value.lower() not in lowered)
    unique = tuple(dict.fromkeys(expansions))[:8]
    rewritten = " ".join((original, *unique)).strip()[:1600]
    return QueryRewrite(original, rewritten, unique, False)
