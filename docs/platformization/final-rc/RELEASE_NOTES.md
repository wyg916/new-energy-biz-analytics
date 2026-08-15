# 4.1.0-integration-full.1 Final RC release notes

This release freezes the already accepted Full Integration functional baseline. The Final RC audit adds no business feature, UI layout change, SQLBot routing change, RAG tuning, Memory redesign, or P6 workflow.

Validated release boundary:

- PostgreSQL-backed API and frontend data chain with DQ28 PASS.
- 17 governed Knowledge documents and complete published/current indexing.
- Hybrid RAG fixed evaluation and live retrieval lifecycle.
- Memory40, Skill40, lifecycle, Redis, deletion and scheduler gates.
- Deterministic ChatBI for all formal user traffic.
- Kimi, MiMo and DeepSeek available through ModelGateway for approved non-SQL tasks.
- SQLBot remains registered but not eligible; `SQLBOT_ENGINE_ENABLED=false`.
- Alert, report and metric-governance P6 loops with RBAC, audit and immutable evidence snapshots.
- OIDC Authorization Code + PKCE and Vault sealed recovery.

The complete machine-readable result is `evidence/final-rc-audit-summary.json`. No tag is created by this audit.

## Post-audit status

After the audit closed, the project owner separately authorized creation of the
annotated tag `final-rc-v4.1.0-integration-full.1` and entry into the Release
approval/artifact-archive stage. The source archive is derived from that exact
tag and is described by `release-archive-manifest.json`.

This authorization did not create a GitHub Release, perform a deployment,
switch production traffic, or authorize deletion of the tag.
