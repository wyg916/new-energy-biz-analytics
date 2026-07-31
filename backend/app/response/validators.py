from app.response.citations import validate_claim_bindings
from app.response.contracts import CompositionRequest


def validate_composition_request(request: CompositionRequest) -> None:
    if request.data_evidence is None and request.knowledge_evidence is None:
        return
    if request.data_evidence is not None:
        if request.data_evidence.run_id != request.run_id:
            raise ValueError("data evidence run_id does not match response run_id")
        for metric in request.data_evidence.key_metrics:
            if not metric.source:
                raise ValueError("every metric must retain a structured-result source")
    if request.knowledge_evidence is not None:
        validate_claim_bindings(request.knowledge_evidence)
