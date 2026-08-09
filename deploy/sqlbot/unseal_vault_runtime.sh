#!/bin/sh
set -eu

export VAULT_ADDR="${VAULT_ADDR:-http://vault:8200}"
runtime_root="${P4_RUNTIME_ROOT:-/run/p4-runtime}"
vault operator unseal "$(cat "$runtime_root/vault_unseal_key")" >/dev/null
sealed="$(vault status -format=json | sed -n 's/.*"sealed": *\([^,]*\).*/\1/p')"
test "$sealed" = "false"
echo '{"status":"PASS","sealed":false,"secret_values_exposed":false}'
