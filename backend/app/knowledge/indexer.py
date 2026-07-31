"""P2A index contract.

Keyword/full-text chunks are persisted in the primary database. The current
PostgreSQL image has no pgvector extension, so vector indexing remains an
explicit VECTOR_PENDING capability rather than a simulated implementation.
"""

VECTOR_STATUS = "VECTOR_PENDING"
