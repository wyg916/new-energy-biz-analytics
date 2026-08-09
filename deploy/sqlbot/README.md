# SQLBot isolated local deployment

This directory contains only the deployment boundary for the upstream SQLBot
runtime. SQLBot source code is not copied into the platform core.

## Pinned upstream

- repository: `dataease/SQLBot`
- release: `v1.10.0`
- image reference: `registry.cn-qingdao.aliyuncs.com/dataease/sqlbot:v1.10.0`
- local acceptance source: the official offline installer supplied outside this
  repository; no installer payload is copied or coupled into the platform

Do not replace the image reference with `main` or `latest`.

## Network and access boundary

- The administration UI is bound only to `127.0.0.1:18080`.
- The platform backend reaches SQLBot through the private
  `renewable-sqlbot-proxy` Docker network.
- The React application never receives SQLBot credentials, tokens, or internal
  chat identifiers.
- SQLBot must use a dedicated read-only datasource exposing only the approved
  semantic views for simulated data.
- This deployment must not use the platform writable application account.

The upstream image currently requires privileged local-container operation.
This is accepted only for isolated local evaluation and is a blocking reason
against production deployment.

## Secrets

Copy `sqlbot.env.example` to an untracked local file and populate it through a
controlled local secret mechanism. Never commit the populated file.

The Compose file deliberately fails configuration when any required secret is
missing. It does not contain an upstream default password or a generated secret.

The service entrypoint is the repository-owned
`start-local-acceptance.sh`. It extends the bounded bundled-PostgreSQL readiness
window to 15 minutes and supervises a graceful database shutdown. This avoids
the upstream fixed startup window and prevents a normal container restart from
creating another crash-recovery cycle. The health check remains an actual HTTP
probe; the extended `start_period` is not a readiness bypass.

The mounted `sqlbot41_runtime.py` adds only
`POST /api/v1/mcp/mcp_generate_sql`. It invokes SQLBot v1.10.0 with its native
`GENERATE_SQL` finish step and therefore returns before SQLBot's datasource
execution step. The platform Adapter calls only this route, then applies Query
Guard and the platform read-only executor. The upstream execution-capable MCP
route is not part of the platform integration contract.

SQLBot v1.10 converts a structured model refusal into an HTTP 500 on its
non-stream route. The thin route preserves only an exact `success:false`
envelope as a pre-SQL refusal; all other HTTP/runtime failures remain failures.
No upstream model prose is forwarded into audit evidence.

4.1C acceptance resolves the runtime account through governed
CredentialReferences. A domain-separated HMAC adapter produces a value that
meets SQLBot's local 8--20 character password policy without storing or
printing the referenced secret. Missing or stale references fail closed and do
not fall back to unregistered environment credentials.

## Start and verify

Create the shared proxy network once, then start the isolated stack:

```text
docker network create renewable-sqlbot-proxy
docker compose --env-file <untracked-local-env> -f deploy/sqlbot/compose.yaml up -d
docker compose --env-file <untracked-local-env> -f deploy/sqlbot/compose.yaml ps
```

Acceptance startup order is: bundled PostgreSQL ready, SQLBot SSR/MCP, SQLBot
HTTP API. `restart: unless-stopped` restarts an abnormal application exit. A
normal `docker compose stop` allows the supervisor to stop PostgreSQL cleanly.

The 4.1C evidence records real v1.10 HTTP generation against locally configured
simulated DATA-4.1 semantic datasources. A Mock Server result is never evidence
of upstream runtime health or Shadow eligibility. Current quality and latency
gates are recorded separately from platform contract tests.
