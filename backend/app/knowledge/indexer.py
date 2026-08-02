"""P2A index contract.

Keyword/full-text chunks are persisted in the primary database. The current
PostgreSQL image has no pgvector extension, so P5 formally freezes retrieval
as keyword-only and defers vector indexing rather than simulating a release.
"""

VECTOR_STATUS = "VECTOR_DEFERRED_POST_P5"
