#!/bin/sh
set -eu

export VAULT_ADDR="${VAULT_ADDR:-http://vault:8200}"
runtime_root="${P4_RUNTIME_ROOT:-/run/p4-runtime}"

vault operator generate-root -cancel >/dev/null 2>&1 || true
vault operator generate-root -init -format=json >/tmp/p4-vault-root-init.json
nonce="$(sed -n 's/.*"nonce": "\([^"]*\)".*/\1/p' /tmp/p4-vault-root-init.json)"
otp="$(sed -n 's/.*"otp": "\([^"]*\)".*/\1/p' /tmp/p4-vault-root-init.json)"
unseal_key="$(head -n 1 "$runtime_root/vault_unseal_key")"
test -n "$nonce"
test -n "$otp"
test -n "$unseal_key"
vault operator generate-root -nonce="$nonce" "$unseal_key" -format=json >/tmp/p4-vault-root-update.json
encoded="$(sed -n 's/.*"encoded_token": "\([^"]*\)".*/\1/p' /tmp/p4-vault-root-update.json)"
test -n "$encoded"
vault operator generate-root -decode="$encoded" -otp="$otp" >"$runtime_root/vault_recovery_root"
chmod 0600 "$runtime_root/vault_recovery_root"
test -s "$runtime_root/vault_recovery_root"
echo '{"status":"STAGED","secret_value_printed":false,"purpose":"interrupted-bootstrap-recovery"}'
