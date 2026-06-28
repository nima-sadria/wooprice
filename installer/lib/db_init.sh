#!/usr/bin/env bash
# WooPrice Beta — Database initialization and migration runner (BU1)
#
# Source from install.sh. Requires:
#   - PostgreSQL container healthy (call wait_for_postgres_ready first)
#   - BETA_POSTGRES_USER, BETA_POSTGRES_DB exported in environment
#
# Migration conditions (per Owner approval, 2026-06-28):
#   - Runs ONLY after PostgreSQL is healthy
#   - Failure stops installation with clear diagnostics
#   - No rollback logic
#   - Targets Beta environment ONLY (never production)

set -euo pipefail

run_alembic_migrations() {
    local install_dir="$1"
    local compose_file="${install_dir}/docker-compose.beta.yml"
    local dc_cmd

    if docker compose version &>/dev/null 2>&1; then
        dc_cmd="docker compose"
    elif command -v docker-compose &>/dev/null; then
        dc_cmd="docker-compose"
    else
        echo "  ERROR: docker compose not available" >&2
        return 1
    fi

    echo "  Running Alembic database migrations..."
    echo "  Command: alembic -c alembic_beta.ini upgrade head"

    if ! ${dc_cmd} -f "$compose_file" exec -T app \
        alembic -c alembic_beta.ini upgrade head; then
        echo "" >&2
        echo "  ERROR: Alembic migration failed." >&2
        echo "  This is a fatal error — installation cannot continue." >&2
        echo "" >&2
        echo "  Diagnostics:" >&2
        echo "    docker compose -f ${compose_file} logs app" >&2
        echo "    docker compose -f ${compose_file} exec app alembic -c alembic_beta.ini current" >&2
        return 1
    fi

    echo "  Migrations complete."
}
