#!/usr/bin/env bash
# WooPrice Beta — Docker Compose file generation (B4 Installer Foundation)
#
# Generates docker-compose.beta.yml by substituting BETA_* placeholders in
# installer/templates/docker-compose.template.yml using envsubst.
# Does NOT start any Docker services — that is B6 (Docker Runtime Foundation).

set -euo pipefail

generate_compose_file() {
    local template_path="$1"
    local output_path="$2"

    if [[ ! -f "$template_path" ]]; then
        echo "  ERROR: Compose template not found: ${template_path}" >&2
        return 1
    fi

    if ! command -v envsubst &>/dev/null; then
        echo "  ERROR: envsubst not found (install gettext package)" >&2
        return 1
    fi

    # Substitute only BETA_* variables from environment
    # shellcheck disable=SC2016
    envsubst '${BETA_ENV} ${BETA_DOMAIN} ${BETA_PORT} ${BETA_DATABASE_URL}
              ${BETA_POSTGRES_DB} ${BETA_POSTGRES_USER} ${BETA_POSTGRES_PASSWORD}
              ${BETA_JWT_SECRET} ${BETA_REST_API_SECRET}' \
        < "$template_path" > "$output_path"

    echo "  Docker Compose file generated: ${output_path}"
    echo "  NOTE: Docker stack launch is implemented in B6 (Docker Runtime Foundation)."
    echo "  To launch manually: docker compose -f ${output_path} up -d"
}
