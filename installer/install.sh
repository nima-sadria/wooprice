#!/usr/bin/env bash
# WooPrice Beta — Main installer entry point (B4 Foundation)
#
# Usage:
#   bash install.sh [--dry-run] [--install-dir <path>] [--non-interactive]
#
# B4 scope: prerequisite checks, wizard, secrets, .env, TOML config,
#           storage setup, dry-run mode, rollback.
# B6 scope: Docker stack launch, health checks.
# B7 scope: Admin account creation.
#
# Do NOT run this against a production environment.
# [BETA ENVIRONMENT — NOT PRODUCTION]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/lib"
TEMPLATES_DIR="${SCRIPT_DIR}/templates"

# Source all lib modules
# shellcheck source=installer/lib/checks.sh
source "${LIB_DIR}/checks.sh"
# shellcheck source=installer/lib/secrets.sh
source "${LIB_DIR}/secrets.sh"
# shellcheck source=installer/lib/wizard.sh
source "${LIB_DIR}/wizard.sh"
# shellcheck source=installer/lib/env_gen.sh
source "${LIB_DIR}/env_gen.sh"
# shellcheck source=installer/lib/storage.sh
source "${LIB_DIR}/storage.sh"
# shellcheck source=installer/lib/compose_gen.sh
source "${LIB_DIR}/compose_gen.sh"

# ---- Defaults ----
INSTALL_DIR="${HOME}/wooprice-beta"
DRY_RUN=0
NON_INTERACTIVE=0
INSTALLER_ENV_FILE=""
INSTALLER_CREATED_FILES=""   # space-separated, for file rollback

# ---- Argument parsing ----
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)           DRY_RUN=1 ;;
        --non-interactive)   NON_INTERACTIVE=1 ;;
        --install-dir)       INSTALL_DIR="$2"; shift ;;
        --install-dir=*)     INSTALL_DIR="${1#*=}" ;;
        -h|--help)
            echo "Usage: bash install.sh [--dry-run] [--install-dir DIR]"
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
    shift
done

INSTALLER_ENV_FILE="${INSTALL_DIR}/.env"

# ---- Rollback ----
_track_file() { INSTALLER_CREATED_FILES="${INSTALLER_CREATED_FILES} $1"; }

rollback_all() {
    echo ""
    echo "  !! Rolling back installation (removing only files/dirs created by this run)..."
    # Rollback storage directories (tracked in storage.sh)
    rollback_storage 2>/dev/null || true
    # Rollback generated files
    for f in $INSTALLER_CREATED_FILES; do
        if [[ -f "$f" ]]; then
            rm -f "$f"
            echo "  Removed file: ${f}"
        fi
    done
    echo "  Rollback complete."
}

# ---- Error handler ----
on_error() {
    local exit_code=$?
    local line_no="${1:-?}"
    echo ""
    echo "  !! Installation failed at line ${line_no} (exit code: ${exit_code})"
    if [[ "$DRY_RUN" -eq 0 ]]; then
        rollback_all
    fi
    echo ""
    echo "  To retry: re-run install.sh"
    echo "  Install log: ${INSTALL_DIR}/install.log (if storage was created)"
    exit "$exit_code"
}
trap 'on_error $LINENO' ERR

# ---- Welcome banner ----
print_banner() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  WooPrice Beta Installer  v1.0.0-b4"
    echo "  [BETA ENVIRONMENT — NOT PRODUCTION]"
    echo ""
    echo "  This installer sets up a completely isolated Beta environment."
    echo "  It will NOT modify any Production WooPrice installation."
    echo ""
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "  *** DRY-RUN MODE — No files will be written ***"
    fi
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# ---- Step 1: Prerequisite checks ----
step_prerequisites() {
    echo ""
    echo "Step 1 — Prerequisite Checks"
    run_prerequisite_checks "$INSTALL_DIR"
}

# ---- Step 2: Interactive wizard ----
step_wizard() {
    if [[ "$NON_INTERACTIVE" -eq 0 ]]; then
        echo ""
        echo "Step 2 — Interactive Configuration Wizard"
        run_wizard
    else
        echo "Step 2 — Skipped (--non-interactive)"
    fi
}

# ---- Step 3: Secret generation ----
step_secrets() {
    echo ""
    echo "Step 3 — Secret Generation"
    generate_all_secrets
}

# ---- Step 4: .env file generation + validation ----
step_env_file() {
    echo ""
    echo "Step 4 — Environment File Generation"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "  [DRY RUN] Would write: ${INSTALLER_ENV_FILE}"
        echo "  [DRY RUN] Would call B3 ConfigValidator on generated content"
        return
    fi
    mkdir -p "$INSTALL_DIR"
    generate_env_file "$INSTALLER_ENV_FILE"
    _track_file "$INSTALLER_ENV_FILE"
    validate_env_file "$INSTALLER_ENV_FILE"
}

# ---- Step 5: Managed TOML config generation ----
step_toml_config() {
    echo ""
    echo "Step 5 — Managed Configuration File"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "  [DRY RUN] Would write: ${BETA_STORAGE_PATH}/config/wooprice-beta.toml"
        return
    fi
    python3 - <<PYEOF
import sys
sys.path.insert(0, "${SCRIPT_DIR}/..")
from installer.installer_core import InstallerConfig, generate_toml_content, write_toml_config
from pathlib import Path

config = InstallerConfig(
    domain="${BETA_DOMAIN:-}",
    port=int("${BETA_PORT:-8080}"),
    ssl_mode="${BETA_SSL_MODE:-off}",
    postgres_db="${BETA_POSTGRES_DB:-wooprice_beta}",
    postgres_user="${BETA_POSTGRES_USER:-wooprice_beta}",
    storage_path="${BETA_STORAGE_PATH:-/opt/wooprice-beta/storage}",
    backup_path="${BETA_BACKUP_PATH:-/opt/wooprice-beta/backups}",
    log_level="INFO",
)
content = generate_toml_content(config)
config_dir = Path("${BETA_STORAGE_PATH:-/opt/wooprice-beta/storage}/config")
path = write_toml_config(content, config_dir)
print(f"  Managed config written: {path}")
PYEOF
}

# ---- Step 6: Storage directory setup ----
step_storage() {
    echo ""
    echo "Step 6 — Storage Directory Setup"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "  [DRY RUN] Would create:"
        echo "  ${BETA_STORAGE_PATH:-/opt/wooprice-beta/storage}/{logs,config,plugins,uploads,diagnostics}"
        echo "  ${BETA_BACKUP_PATH:-/opt/wooprice-beta/backups}"
        return
    fi
    setup_storage_dirs
}

# ---- Step 7: Docker Compose file generation ----
step_compose() {
    echo ""
    echo "Step 7 — Docker Compose File Generation"
    local compose_out="${INSTALL_DIR}/docker-compose.beta.yml"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "  [DRY RUN] Would write: ${compose_out}"
        return
    fi
    generate_compose_file \
        "${TEMPLATES_DIR}/docker-compose.template.yml" \
        "$compose_out"
    _track_file "$compose_out"
}

# ---- Steps 8-13: Not implemented in B4 ----
step_docker_launch() {
    echo ""
    echo "Step 8 — Docker Stack Launch"
    echo "  NOT IMPLEMENTED IN B4."
    echo "  Implementation: B6 (Docker Runtime Foundation)"
    echo "  To launch manually after B6: docker compose -f ${INSTALL_DIR}/docker-compose.beta.yml up -d"
}

step_database_init() {
    echo ""
    echo "Step 9 — Database Initialization"
    echo "  NOT IMPLEMENTED IN B4."
    echo "  Implementation: B6 (Docker Runtime Foundation)"
}

step_admin_account() {
    echo ""
    echo "Step 10 — Admin Account Creation"
    echo "  NOT IMPLEMENTED IN B4."
    echo "  Implementation: B7 (Authentication Foundation)"
}

step_ssl_setup() {
    echo ""
    echo "Step 11 — SSL Setup"
    echo "  NOT IMPLEMENTED IN B4."
    echo "  Implementation: B6 (Docker Runtime Foundation)"
}

step_health_check() {
    echo ""
    echo "Step 12 — Health Check"
    echo "  NOT IMPLEMENTED IN B4."
    echo "  Implementation: B6 (Docker Runtime Foundation)"
}

step_completion_report() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "  WooPrice Beta — Dry Run Complete"
        echo "  No files were written. Review the output above."
    else
        echo "  WooPrice Beta — B4 Foundation Steps Complete"
        echo "  Environment file: ${INSTALLER_ENV_FILE}"
        echo "  Config:           ${BETA_STORAGE_PATH:-/opt/wooprice-beta/storage}/config/wooprice-beta.toml"
        echo ""
        echo "  Next steps:"
        echo "  1. Complete B6 (Docker Runtime Foundation) to launch the stack"
        echo "  2. Complete B7 (Authentication Foundation) to create admin account"
        echo "  3. Run: wooprice health all"
    fi
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# ---- Main ----
main() {
    print_banner
    step_prerequisites
    step_wizard
    step_secrets
    step_env_file
    step_storage
    step_toml_config
    step_compose
    step_docker_launch
    step_database_init
    step_admin_account
    step_ssl_setup
    step_health_check
    step_completion_report
}

main "$@"
