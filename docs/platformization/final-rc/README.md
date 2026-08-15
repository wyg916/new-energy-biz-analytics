# Final RC audit

This directory closes the feature-frozen `4.1.0-integration-full.1` release-candidate audit.

- Product baseline: `b6be894a7153f7ce8d31dfc65da7222bd7af1b5f`
- Branch: `codex/integration-4.1-full`
- Query engine: `DETERMINISTIC_ONLY`
- SQLBot: `REGISTERED_NOT_ELIGIBLE`, disabled for user traffic
- Evidence: `evidence/rc-evidence-manifest.json`
- Rollback: `evidence/rc-rollback.json`
- Release manifest: `evidence/rc-release-manifest.json`

The audit does not create a tag. `RC_TAG_ALLOWED=YES` is only an authorization recommendation for the project owner.

The builder is fail closed:

```powershell
py -3 scripts/build_final_rc_audit.py --secret-scan-status PASS
```

The retained `raw/playwright-all.raw.xml` is the interrupted repository-wide historical phase collection. It contains superseded local-login and phase-state contracts and is not the Final RC suite. The current RC suite is the three authoritative specs recorded in `rc-playwright.json`; no historical spec was deleted, skipped, or weakened.

## Post-audit release authorization

The project owner subsequently authorized the annotated tag
`final-rc-v4.1.0-integration-full.1` and the Release approval/artifact-archive
stage. The tag resolves to the audit evidence commit
`ce0764be9c92c7433fae54a62e247736708ea7e5`; the frozen product baseline
remains `b6be894a7153f7ce8d31dfc65da7222bd7af1b5f`.

- Human-readable approval: `RELEASE_APPROVAL.md`
- Machine-readable approval: `release-approval.json`
- Archive manifest: `release-archive-manifest.json`
- GitHub Release: not created
- Deployment and production traffic switch: not performed
- Tag rollback: requires a separate project-owner authorization
