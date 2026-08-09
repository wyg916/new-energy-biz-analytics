"""Prepare DATA 4.1 and enforce Governed Hybrid RAG V1 index readiness."""

from __future__ import annotations

import json

from scripts.prepare_data41 import main as prepare_data41
from scripts.rebuild_rag_indexes import ensure_indexes


def main() -> None:
    # prepare_data41 verifies EXPECTED_DATABASE_REVISION before any business init.
    prepare_data41()
    index_result = ensure_indexes()
    if not index_result["index_ready"]:
        raise RuntimeError("RAG index rebuild did not reach a complete, current state")
    print(json.dumps({
        "status": "PASS",
        "capability": "Governed Hybrid RAG V1",
        "rag_index": index_result,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
