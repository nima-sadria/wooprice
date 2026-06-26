#!/usr/bin/env bash
# WooPrice Beta — Interactive setup wizard (B4 Installer Foundation)
#
# Source from install.sh. Call run_wizard to populate all BETA_* variables.
# Each prompt shows a description, current default, and validation hint.
# User may press Ctrl+C at any point before the confirmation step to abort.

set -euo pipefail

_prompt() {
    # _prompt VAR_NAME "Description" "Default value"
    local var_name="$1" description="$2" default_val="${3:-}"
    local prompt_str
    if [[ -n "$default_val" ]]; then
        prompt_str="  ${description} [${default_val}]: "
    else
        prompt_str="  ${description}: "
    fi
    local value
    read -r -p "$prompt_str" value
    value="${value:-$default_val}"
    printf -v "$var_name" '%s' "$value"
}

_prompt_secret() {
    local var_name="$1" description="$2" offer_generate="${3:-y}"
    if [[ "$offer_generate" == "y" ]]; then
        echo "  ${description}"
        echo "  Press Enter to auto-generate (recommended), or type your own:"
        local value
        read -r -s -p "  > " value
        echo ""
        printf -v "$var_name" '%s' "$value"
    else
        local value
        read -r -s -p "  ${description}: " value
        echo ""
        printf -v "$var_name" '%s' "$value"
    fi
}

_section_header() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Section $1 — $2"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

wizard_section_network() {
    _section_header "1" "Network"
    _prompt BETA_DOMAIN \
        "Beta domain (e.g., beta.yourdomain.com)" ""
    _prompt BETA_PORT \
        "Beta port" "8080"
    echo "  SSL mode options: off / self-signed / letsencrypt / manual"
    _prompt BETA_SSL_MODE \
        "SSL mode" "off"
}

wizard_section_database() {
    _section_header "2" "Database"
    _prompt BETA_POSTGRES_DB   "PostgreSQL database name" "wooprice_beta"
    _prompt BETA_POSTGRES_USER "PostgreSQL username"      "wooprice_beta"
    echo "  PostgreSQL password — press Enter to auto-generate (recommended):"
    _prompt_secret BETA_POSTGRES_PASSWORD "PostgreSQL password" "y"
}

wizard_section_secrets() {
    _section_header "3" "Application Secrets"
    echo "  JWT signing key — press Enter to auto-generate (strongly recommended):"
    _prompt_secret BETA_JWT_SECRET "JWT secret (min 64 chars)" "y"
    echo "  REST API secret — press Enter to auto-generate (strongly recommended):"
    _prompt_secret BETA_REST_API_SECRET "REST API secret (min 32 chars)" "y"
}

wizard_section_source() {
    _section_header "4" "Nextcloud Source"
    _prompt BETA_NEXTCLOUD_URL       "Nextcloud base URL (https://...)" ""
    _prompt BETA_NEXTCLOUD_FILE_PATH "Spreadsheet path in Nextcloud (e.g., /prices/wooprice.xlsx)" ""
    _prompt BETA_NEXTCLOUD_USERNAME  "Nextcloud username" ""
    _prompt_secret BETA_NEXTCLOUD_PASSWORD "Nextcloud password" "n"
}

wizard_section_woocommerce() {
    _section_header "5" "WooCommerce"
    echo "  Use your WooCommerce TEST store only — not the production store."
    _prompt BETA_WOOCOMMERCE_URL "WooCommerce store URL (https://...)" ""
    _prompt_secret BETA_WOOCOMMERCE_KEY "WooCommerce consumer key (ck_...)" "n"
    _prompt_secret BETA_WOOCOMMERCE_SECRET "WooCommerce consumer secret (cs_...)" "n"
}

wizard_section_environment() {
    _section_header "6" "Environment"
    _prompt BETA_TIMEZONE "Timezone (IANA format, e.g., Europe/Amsterdam)" "UTC"
    _prompt BETA_CURRENCY "Default currency (ISO 4217, e.g., EUR, USD)"    "USD"
}

wizard_section_admin() {
    _section_header "7" "Admin Account"
    _prompt BETA_ADMIN_EMAIL "Admin email address" ""
}

wizard_section_storage() {
    _section_header "8" "Storage Paths"
    _prompt BETA_STORAGE_PATH "Storage base path" "/opt/wooprice-beta/storage"
    _prompt BETA_BACKUP_PATH  "Backup path"       "/opt/wooprice-beta/backups"
}

wizard_section_confirm() {
    _section_header "9" "Confirmation"

    local masked_jwt masked_rest masked_pg
    masked_jwt="********${BETA_JWT_SECRET: -4}"
    masked_rest="********${BETA_REST_API_SECRET: -4}"
    masked_pg="${BETA_POSTGRES_PASSWORD:+********${BETA_POSTGRES_PASSWORD: -4}}"
    masked_pg="${masked_pg:-[will be generated]}"

    echo ""
    echo "  Installation Summary:"
    echo "  Domain:          ${BETA_DOMAIN}:${BETA_PORT}"
    echo "  SSL mode:        ${BETA_SSL_MODE}"
    echo "  Postgres DB:     ${BETA_POSTGRES_DB}"
    echo "  Postgres user:   ${BETA_POSTGRES_USER}"
    echo "  Postgres pass:   ${masked_pg}"
    echo "  JWT secret:      ${masked_jwt:=[will be generated]}"
    echo "  REST secret:     ${masked_rest:=[will be generated]}"
    echo "  Nextcloud URL:   ${BETA_NEXTCLOUD_URL}"
    echo "  WooCommerce URL: ${BETA_WOOCOMMERCE_URL}"
    echo "  Timezone:        ${BETA_TIMEZONE}"
    echo "  Currency:        ${BETA_CURRENCY}"
    echo "  Admin email:     ${BETA_ADMIN_EMAIL}"
    echo "  Storage path:    ${BETA_STORAGE_PATH}"
    echo "  Backup path:     ${BETA_BACKUP_PATH}"
    echo ""

    local answer
    read -r -p "  Proceed with installation? [Y/n]: " answer
    answer="${answer:-y}"
    if [[ "${answer,,}" != "y" && "${answer,,}" != "yes" ]]; then
        echo "  Installation cancelled."
        exit 0
    fi
}

run_wizard() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  WooPrice Beta — Interactive Setup"
    echo "  [BETA ENVIRONMENT — NOT PRODUCTION]"
    echo "  Press Ctrl+C at any time to abort (no files will be written)."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    wizard_section_network
    wizard_section_database
    wizard_section_secrets
    wizard_section_source
    wizard_section_woocommerce
    wizard_section_environment
    wizard_section_admin
    wizard_section_storage
    wizard_section_confirm
}
