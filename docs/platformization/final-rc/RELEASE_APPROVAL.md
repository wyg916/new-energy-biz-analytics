# Final RC Release approval and artifact archive

Status: **APPROVED FOR RELEASE ARCHIVAL**

This record captures the project owner's explicit authorization to enter the
Release approval and artifact-archive stage for
`4.1.0-integration-full.1`.

## Immutable release identity

- Branch: `codex/integration-4.1-full`
- Frozen product baseline: `b6be894a7153f7ce8d31dfc65da7222bd7af1b5f`
- Final audit evidence commit: `ce0764be9c92c7433fae54a62e247736708ea7e5`
- Annotated tag: `final-rc-v4.1.0-integration-full.1`
- Tag object: `e5c5ba8be4df599d6a6f2ea3e9b06df283b61b81`
- Tag target: `ce0764be9c92c7433fae54a62e247736708ea7e5`

## Approved scope

- Preserve the Release approval as a repository audit record.
- Generate a source ZIP from the exact annotated tag.
- Record the ZIP path, SHA-256, size and content checks.
- Preserve the existing Final RC evidence and rollback manifests unchanged.

## Explicit exclusions

- No GitHub Release was created.
- No deployment or production traffic switch was performed.
- No business code, UI, database migration or runtime configuration was changed.
- No tag deletion, retargeting or force update was authorized.

Tag rollback requires a separate explicit authorization from the project owner.
The machine-readable scope and verification evidence are in
`release-approval.json` and `release-archive-manifest.json`.

The `tag_created=false` fields retained inside the earlier audit evidence remain
historically correct: the audit itself did not create a tag and required a
subsequent owner authorization. This post-audit record does not rewrite those
immutable audit artifacts.
