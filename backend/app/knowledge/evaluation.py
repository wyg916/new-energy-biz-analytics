from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalMetrics:
    recall_at_k: float
    mean_reciprocal_rank: float
    citation_accuracy: float
    unauthorized_retrievals: int
    unpublished_retrievals: int
    injection_effects: int
