#!/usr/bin/env bash
# WooPrice Beta — Main installer entry point (BU1)
#
# Usage:
#   bash installer/install.sh [--install-dir <path>] [--dry-run] [--non-interactive]
#
# Idempotent: detects existing installations and offers upgrade/repair/reconfigure/exit.
# Never overwrites an existing .env.beta without explicit confirmation.
#
# [BETA ENVIRONMENT — NOT PRODUCTION]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/lib"
TEMPLATES_DIR="${SCRIPT_DIR}/templates"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Source lib modules
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
# shellcheck source=installer/lib/docker_deploy.sh
source "${LIB_DIR}/docker_deploy.sh"
# shellcheck source=installer/lib/db_init.sh
source "${LIB_DIR}/db_init.sh"

# ---- Defaults ----
INSTALL_DIR="/opt/wooprice-beta"
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
            echo "Usage: bash installer/install.sh [--dry-run] [--install-dir DIR] [--non-interactive]"
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
    shift
done

INSTALLER_ENV_FILE="${INSTALL_DIR}/.env.beta"

# ---- Rollback ----
_track_file() { INSTALLER_CREATED_FILES="${INSTALLER_CREATED_FILES} $1"; }

rollback_all() {
    echo ""
    echo "  !! Rolling back installation (removing only files/dirs created by this run)..."
    rollback_storage 2>/dev/null || true
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
    echo "  To diagnose: docker compose -f ${INSTALL_DIR}/docker-compose.beta.yml logs"
    echo "  To retry:    re-run install.sh"
    exit "$exit_code"
}
trap 'on_error $LINENO' ERR

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

print_banner() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  WooPrice Beta Installer  v1.0.0-bu1"
    echo "  [BETA ENVIRONMENT — NOT PRODUCTION]"
    echo ""
    echo "  This installer sets up a completely isolated Beta environment."
    echo "  It will NOT modify any Production WooPrice installation."
    echo ""
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "  *** DRY-RUN MODE — No files will be written, no Docker started ***"
    fi
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# ---------------------------------------------------------------------------
# Idempotency — detect existing installation
# ---------------------------------------------------------------------------

detect_existing_installation() {
    [[ -f "${INSTALLER_ENV_FILE}" ]]
}

handle_existing_installation() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Existing WooPrice Beta installation detected."
    echo "  Environment file: ${INSTALLER_ENV_FILE}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "  Select an action:"
    echo ""
    echo "  1. Upgrade   — rebuild images and restart the stack (keeps .env.beta)"
    echo "  2. Repair    — re-run prerequisite checks and health verification"
    echo "  3. Reconfigure — re-run wizard, regenerate .env.beta, then upgrade"
    echo "  4. Exit"
    echo ""
    local choice
    read -r -p "  Enter choice [1-4]: " choice
    case "${choice:-}" in
        1) step_upgrade ;;
        2) step_repair ;;
        3) step_reconfigure ;;
        4|"")
            echo "  Exiting without changes."
            exit 0
            ;;
        *)
            echo "  Invalid choice. Exiting."
            exit 1
            ;;
    esac
}

# ---- Upgrade path (keeps existing .env.beta) ----
step_upgrade() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Upgrade: rebuilding images and restarting services"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    _load_env_for_docker
    step_docker_launch
    step_database_init
    step_health_check
    step_completion_report
}

# ---- Repair path ----
step_repair() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Repair: re-checking prerequisites and health"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    _load_env_for_docker
    step_prerequisites
    step_storage
    step_health_check
    echo ""
    echo "  Repair complete."
}

# ---- Reconfigure path ----
step_reconfigure() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Reconfigure: wizard will regenerate .env.beta"
    echo "  EXISTING .env.beta WILL BE OVERWRITTEN after confirmation."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    local confirm
    read -r -p "  Continue? Secrets will be regenerated. [y/N]: " confirm
    if [[ "${confirm,,}" != "y" && "${confirm,,}" != "yes" ]]; then
        echo "  Reconfiguration cancelled."
        exit 0
    fi
    step_wizard
    step_secrets
    step_env_file
    step_storage
    step_docker_launch
    step_database_init
    step_health_check
    step_completion_report
}

# Load .env.beta into shell for use by Docker deploy functions
_load_env_for_docker() {
    if [[ -f "${INSTALLER_ENV_FILE}" ]]; then
        # Export only BETA_* vars; skip comments and blank lines
        while IFS='=' read -r key value; do
            [[ "$key" =~ ^#.*$ || -z "$key" ]] && continue
            [[ "$key" =~ ^BETA_ ]] && export "$key=$value"
        done < <(grep -E '^BETA_' "${INSTALLER_ENV_FILE}" 2>/dev/null || true)
    fi
}

# ---------------------------------------------------------------------------
# Installation steps
# ---------------------------------------------------------------------------

step_prerequisites() {
    echo ""
    echo "Step 1 — Prerequisite Checks"
    run_prerequisite_checks "$INSTALL_DIR"
}

step_wizard() {
    if [[ "$NON_INTERACTIVE" -eq 0 ]]; then
        echo ""
        echo "Step 2 — Interactive Configuration Wizard"
        run_wizard
    else
        echo "Step 2 — Skipped (--non-interactive)"
    fi
}

step_secrets() {
    echo ""
    echo "Step 3 — Secret Generation"
    generate_all_secrets
}

step_env_file() {
    echo ""
    echo "Step 4 — Environment File Generation"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "  [DRY RUN] Would write: ${INSTALLER_ENV_FILE}"
        echo "  [DRY RUN] Would validate configuration using B3 ConfigValidator"
        return
    fi
    mkdir -p "$INSTALL_DIR"
    generate_env_file "$INSTALLER_ENV_FILE"
    _track_file "$INSTALLER_ENV_FILE"
    validate_env_file "$INSTALLER_ENV_FILE"
}

step_storage() {
    echo ""
    echo "Step 5 — Storage Directory Setup"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "  [DRY RUN] Would create:"
        echo "  ${BETA_STORAGE_PATH:-/opt/wooprice-beta/storage}/{logs,config,plugins,uploads,diagnostics}"
        echo "  ${BETA_BACKUP_PATH:-/opt/wooprice-beta/backups}"
        echo "  ${INSTALL_DIR}/logs"
        return
    fi
    setup_storage_dirs
    # Ensure bind-mount directories exist in INSTALL_DIR
    mkdir -p "${INSTALL_DIR}/storage" "${INSTALL_DIR}/backups" "${INSTALL_DIR}/logs"
    echo "  Bind-mount directories ready: storage/ backups/ logs/"
}

step_toml_config() {
    echo ""
    echo "Step 6 — Managed Configuration File"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "  [DRY RUN] Would write: ${BETA_STORAGE_PATH:-/opt/wooprice-beta/storage}/config/wooprice-beta.toml"
        return
    fi
    python3 - <<PYEOF
import sys
sys.path.insert(0, "${REPO_DIR}")
from installer.installer_core import InstallerConfig, generate_toml_content, write_toml_config
from pathlib import Path

config = InstallerConfig(
    domain="${BETA_DOMAIN:-}",
    port=int("${BETA_PORT:-8085}"),
    ssl_mode="${BETA_SSL_MODE:-off}",
    postgres_db="${BETA_POSTGRES_DB:-wooprice_beta}",
    postgres_user="${BETA_POSTGRES_USER:-wooprice_beta}",
    storage_path="${BETA_STORAGE_PATH:-/opt/wooprice-beta/storage}",
    backup_path="${BETA_BACKUP_PATH:-/opt/wooprice-beta/backups}",
    log_level="INFO",
)
content = generate_toml_content(config)
config_dir = Path("${BETA_STORAGE_PATH:-/opt/wooprice-beta/storage}/config")
config_dir.mkdir(parents=True, exist_ok=True)
path = write_toml_config(content, config_dir)
print(f"  Managed config written: {path}")
PYEOF
}

step_compose_verify() {
    echo ""
    echo "Step 7 — Docker Compose Verification"
    local compose_file="${INSTALL_DIR}/docker-compose.beta.yml"
    if [[ -f "$compose_file" ]]; then
        echo "  Compose file: ${compose_file}"
        local dc_cmd
        dc_cmd="$(docker_compose_cmd)"
        if [[ "$DRY_RUN" -eq 0 ]]; then
            ${dc_cmd} -f "$compose_file" --env-file "${INSTALLER_ENV_FILE}" config --quiet \
                && echo "  Compose config: VALID" \
                || { echo "  ERROR: Compose config validation failed" >&2; return 1; }
        else
            echo "  [DRY RUN] Would validate: ${compose_file}"
        fi
    else
        echo "  ERROR: docker-compose.beta.yml not found at ${INSTALL_DIR}" >&2
        echo "  Ensure the repository was cloned to ${INSTALL_DIR}" >&2
        return 1
    fi
}

step_docker_launch() {
    echo ""
    echo "Step 8 — Docker Stack Launch"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "  [DRY RUN] Would run: docker compose build && docker compose up -d"
        return
    fi
    _load_env_for_docker
    build_and_start_services "$INSTALL_DIR"
}

step_database_init() {
    echo ""
    echo "Step 9 — Database Initialization"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "  [DRY RUN] Would wait for PostgreSQL, then run: alembic upgrade head"
        return
    fi
    _load_env_for_docker
    wait_for_postgres_ready "$INSTALL_DIR" 90
    run_alembic_migrations "$INSTALL_DIR"
}

step_install_cli() {
    echo ""
    echo "Step 10 — Install wooprice CLI"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "  [DRY RUN] Would install: /usr/local/bin/wooprice"
        return
    fi
    local wrapper_src="${REPO_DIR}/scripts/wooprice"
    local wrapper_dst="/usr/local/bin/wooprice"
    if [[ ! -f "$wrapper_src" ]]; then
        echo "  WARNING: CLI wrapper not found at ${wrapper_src} — skipping" >&2
        return
    fi
    if [[ -w "$(dirname "$wrapper_dst")" ]] || command -v sudo &>/dev/null; then
        if [[ -w "$(dirname "$wrapper_dst")" ]]; then
            cp "$wrapper_src" "$wrapper_dst"
            chmod +x "$wrapper_dst"
        else
            sudo cp "$wrapper_src" "$wrapper_dst"
            sudo chmod +x "$wrapper_dst"
        fi
        echo "  CLI installed: ${wrapper_dst}"
        echo "  Test with: wooprice --help"
    else
        echo "  WARNING: Cannot write to $(dirname "$wrapper_dst") (no sudo) — CLI not installed"
        echo "  Manual install: cp ${wrapper_src} ${wrapper_dst} && chmod +x ${wrapper_dst}"
    fi
}

step_health_check() {
    echo ""
    echo "Step 11 — Health Verification"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "  [DRY RUN] Would verify: http://localhost:${BETA_PORT:-8085}/api/health"
        return
    fi
    _load_env_for_docker
    local port="${BETA_PORT:-8085}"
    wait_for_app_healthy "$port" 24
    verify_health_endpoint "$port"
}

step_completion_report() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "  WooPrice Beta — Dry Run Complete"
        echo "  No files were written. No Docker was started."
        echo "  Review the output above for a preview of what would happen."
    else
        _load_env_for_docker
        local port="${BETA_PORT:-8085}"
        local domain="${BETA_DOMAIN:-localhost}"
        echo "  WooPrice Beta — Installation Complete"
        echo ""
        echo "  Application:     http://${domain}:${port}"
        echo "  Health endpoint: http://${domain}:${port}/api/health"
        echo "  Environment:     ${INSTALLER_ENV_FILE}"
        echo "  Storage:         ${INSTALL_DIR}/storage"
        echo "  Backups:         ${INSTALL_DIR}/backups"
        echo "  Logs:            ${INSTALL_DIR}/logs"
        echo ""
        echo "  Management:"
        echo "    wooprice              — interactive management menu"
        echo "    wooprice status       — configuration status"
        echo "    wooprice health       — local health checks"
        echo "    wooprice diagnostics run — full integration check"
        echo ""
        echo "  Docker (if direct access needed):"
        echo "    docker compose -f ${INSTALL_DIR}/docker-compose.beta.yml ps"
        echo "    docker compose -f ${INSTALL_DIR}/docker-compose.beta.yml logs -f app"
        echo ""
        echo "  Next steps:"
        echo "    1. Configure your reverse proxy to forward to port ${port}"
        echo "    2. Authentication is implemented in B7"
        echo "    3. UI is implemented in B5"
    fi
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    print_banner

    # Idempotency check — detect existing installation before starting.
    # Non-interactive mode with an existing .env.beta defaults to upgrade to
    # avoid silently overwriting secrets without confirmation.
    if detect_existing_installation && [[ "$DRY_RUN" -eq 0 ]]; then
        if [[ "$NON_INTERACTIVE" -eq 1 ]]; then
            echo "  Existing installation detected. Running upgrade (non-interactive mode)."
            step_upgrade
            return
        fi
        handle_existing_installation
        return
    fi

    step_prerequisites
    step_wizard
    step_secrets
    step_env_file
    step_storage
    step_toml_config
    step_compose_verify
    step_docker_launch
    step_database_init
    step_install_cli
    step_health_check
    step_completion_report
}

main "$@"
