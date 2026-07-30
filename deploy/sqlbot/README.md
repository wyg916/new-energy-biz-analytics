# SQLBot isolated local deployment

This directory contains only the deployment boundary for the upstream SQLBot
runtime. SQLBot source code is not copied into the platform core.

## Pinned upstream

- repository: `dataease/SQLBot`
- release: `v1.8.0`
- release commit shown by the upstream release: `b2de038`
- image reference: `dataease/sqlbot:v1.8.0`

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

## Start and verify

Create the shared proxy network once, then start the isolated stack:

```text
docker network create renewable-sqlbot-proxy
docker compose --env-file <untracked-local-env> -f deploy/sqlbot/compose.yaml up -d
docker compose --env-file <untracked-local-env> -f deploy/sqlbot/compose.yaml ps
```

The current repository records `SQLBOT_RUNTIME_PENDING` until the pinned image
is pulled and its health check and Adapter contract are exercised against a
locally configured simulated datasource. A Mock Server result is never evidence
of upstream runtime health.
