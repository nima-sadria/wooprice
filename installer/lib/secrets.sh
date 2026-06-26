#!/usr/bin/env bash
# WooPrice Beta — Secret generation (B4 Installer Foundation)
#
# Uses openssl rand. Secrets are held in shell variables only.
# Written to .env once by env_gen.sh. Never echoed to terminal in plain text.
# Call generate_all_secrets to populate BETA_JWT_SECRET, BETA_REST_API_SECRET,
# and BETA_POSTGRES_PASSWORD shell variables.

set -euo pipefail

generate_jwt_secret() {
    # 64 bytes of base64url → ~88 chars; always >= 64 chars minimum
    openssl rand -base64 64 | tr -d '\n/+=' | head -c 86
}

generate_rest_api_secret() {
    # 32 bytes hex → 64 chars
    openssl rand -hex 32
}

generate_postgres_password() {
    # 24 bytes base64url → ~32 chars; strip special chars safe for .env
    openssl rand -base64 24 | tr -d '\n/+='
}

_mask_secret() {
    local s="$1"
    local len="${#s}"
    if [[ "$len" -le 4 ]]; then
        echo "****"
    else
        echo "********${s: -4}"
    fi
}

generate_all_secrets() {
    # Populate variables in calling scope — only generate if not already set
    if [[ -z "${BETA_JWT_SECRET:-}" ]]; then
        BETA_JWT_SECRET="$(generate_jwt_secret)"
    fi
    if [[ -z "${BETA_REST_API_SECRET:-}" ]]; then
        BETA_REST_API_SECRET="$(generate_rest_api_secret)"
    fi
    if [[ -z "${BETA_POSTGRES_PASSWORD:-}" ]]; then
        BETA_POSTGRES_PASSWORD="$(generate_postgres_password)"
    fi

    echo "  Secrets generated:"
    echo "  JWT secret:      $(_mask_secret "$BETA_JWT_SECRET")"
    echo "  REST API secret: $(_mask_secret "$BETA_REST_API_SECRET")"
    echo "  Postgres pass:   $(_mask_secret "$BETA_POSTGRES_PASSWORD")"
    echo "  (Secrets will be written to .env once. They will not be displayed again.)"
}
