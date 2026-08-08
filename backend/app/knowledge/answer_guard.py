from __future__ import annotations

from dataclasses import dataclass

from app.knowledge.indexer import tokenize
from app.knowledge.models import Citation
from app.knowledge.security import prompt_injection_detected


@dataclass(frozen=True)
class AnswerGuardResult:
    allowed: bool
    reason: str | None


def guard_grounded_answer(answer: str, citations: tuple[Citation, ...]) -> AnswerGuardResult:
    if not citations:
        return AnswerGuardResult(False, "NO_PUBLISHED_EVIDENCE")
    if prompt_injection_detected(answer):
        return AnswerGuardResult(False, "ANSWER_PROMPT_INJECTION")
    answer_terms = set(tokenize(answer))
    evidence_terms = set(tokenize(" ".join(item.citation_text for item in citations)))
    if answer_terms and not (answer_terms & evidence_terms):
        return AnswerGuardResult(False, "UNGROUNDED_ANSWER")
    return AnswerGuardResult(True, None)
