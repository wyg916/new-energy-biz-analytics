# INTEGRATION-4.1-FULL multi-provider recovery evidence

Status: **PARTIAL**. Kimi K2.6, MiMo V2.5, and DeepSeek V4-Flash all passed
official model discovery, minimal calls, five health probes, SQLBot management API
preflight, and the project's ModelGateway adapter probe. None passed the frozen
SQLBot eligibility gate of Smoke20 20/20 with P95 at or below 15 seconds.

Consequently, all three providers are `REGISTERED_NOT_ELIGIBLE`, no SQLBot
Primary or Standby was selected, formal SQLBot traffic remains disabled, and the
deterministic engine remains the active safe path. Shadow50 and subsequent SQLBot
closure gates were not executed because their provider prerequisite failed.

The historical three DeepSeek failures and all current provider Smoke20 attempts
are retained. Evidence contains only credential references and SHA-256
fingerprints; it does not contain API key values or model response prose.

Rollback is to stop the current SQLBot acceptance container and start the preserved
`renewable-sqlbot-41c-runtime-v1-10-0-pre-multiprovider-20260812` container. No
database volume or existing evidence must be deleted for rollback.
