# INTEGRATION-4.1-FULL deterministic safe-mode closure evidence

Status: **PASS**. `FINAL_RC_CANDIDATE=YES` under the approved deterministic
safe-degraded definition; this is not production release authorization and no RC
tag was created.

Kimi K2.6, MiMo V2.5, and DeepSeek V4-Flash are registered in ModelGateway and
each passed a real runtime response validation. Their SQLBot Smoke20 results stay
frozen and below the unchanged 20/20 plus P95 <= 15 seconds gate. Therefore all
three remain `REGISTERED_NOT_ELIGIBLE`, Primary and Standby remain `NONE`, Open
NL2SQL remains disabled, and no SQLBot production traffic is enabled.

Formal business questions continue through the deterministic Query Engine,
parameterized SQL compiler, Query Guard, read-only PostgreSQL execution,
structured result, and Answer Guard. The true-OIDC safe-mode Playwright journey
verified deterministic ChatBI, scenario switching, governed RAG, memory entry,
and the three P6 closed loops without user-visible ChatBI loss.

The final evidence set includes:

- `sqlbot-safe-degraded-mode.json`: exact provider and disabled-SQLBot state.
- `full-startup-final.json`: 22-step one-click runtime acceptance on committed
  code, including three live ModelGateway provider calls.
- `backend-final-regression.json` and `.xml`: 528/528 tests on isolated tmpfs
  PostgreSQL 16.14 plus real Redis lifecycle.
- `playwright-safe-mode-final.xml`: true-OIDC primary journey PASS.
- `runtime-integration-verification.json`: migration, RAG, Memory, P6, semantic
  views, read-only binding, ModelGateway and deterministic routing checks.
- `knowledge-bootstrap-final.json`: 17 documents, 276 published/indexed chunks,
  and 20 live governed knowledge questions.
- `frontend-truth-scan-final.json`: no fabricated frontend business-data path.
- `secret-scan-final.json`: Trivy secret scan PASS with zero findings.

Historical failed attempts remain evidence, not PASS inputs. Future provider
requalification is isolated to `SQLBOT-PROVIDER-QUALIFICATION`; it must retain
the existing quality and security gates before any Shadow, Canary, or Scoped
Stable activation.

Rollback: revert the Full Integration closure commits, rebuild the two application
images from the previous SHA, and restart the preserved named volumes. Do not
delete database, Vault, OIDC, provider-credential, or evidence volumes.
