from app.response.contracts import CitationEvidence, EvidenceClaim, KnowledgeEvidence


class CitationValidationError(ValueError):
    code = "CITATION_VALIDATION_FAILED"


def validate_claim_bindings(evidence: KnowledgeEvidence) -> None:
    citations = {item.citation_id: item for item in evidence.citations}
    if len(citations) != len(evidence.citations):
        raise CitationValidationError("citation identifiers must be unique")
    for claim in evidence.claims:
        if not claim.citation_ids:
            raise CitationValidationError("every knowledge claim must cite evidence")
        for citation_id in claim.citation_ids:
            citation = citations.get(citation_id)
            if citation is None:
                raise CitationValidationError("claim references an unknown citation")
            if not all((
                citation.document_id,
                citation.document_version_id,
                citation.chunk_id,
                citation.title,
                citation.source,
                citation.published_at,
                citation.citation_text,
            )):
                raise CitationValidationError("citation contract is incomplete")


def citations_for_claims(
    claims: tuple[EvidenceClaim, ...],
    citations: tuple[CitationEvidence, ...],
) -> tuple[CitationEvidence, ...]:
    used = {citation_id for claim in claims for citation_id in claim.citation_ids}
    return tuple(item for item in citations if item.citation_id in used)
