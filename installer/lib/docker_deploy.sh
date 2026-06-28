#!/usr/bin/env bash
# WooPrice Beta — Docker deployment functions (BU1)
#
# Source from install.sh. Provides:
#   docker_compose_cmd()       -- resolve the correct compose CLI
#   build_and_start_services() -- docker compose build + up -d
#   wait_for_postgres_ready()  -- poll pg_isready inside the container
#   wait_for_app_healthy()     -- poll /api/health via curl
#   verify_health_endpoint()   -- final health assertion (fatal on failure)

set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve docker compose command
# ---------------------------------------------------------------------------

docker_compose_cmd() {
    if docker compose version &>/dev/null 2>&1; then
        echo "docker compose"
    elif command -v docker-compose &>/dev/null; then
        echo "docker-compose"
    else
        echo "  ERROR: neither 'docker compose' plugin nor 'docker-compose' found" >&2
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Build images and start the stack
# ---------------------------------------------------------------------------

build_and_start_services() {
    local install_dir="$1"
    local compose_file="${install_dir}/docker-compose.beta.yml"
    local dc_cmd
    dc_cmd="$(docker_compose_cmd)"

    if [[ ! -f "$compose_file" ]]; then
        echo "  ERROR: Compose file not found: ${compose_file}" >&2
        return 1
    fi

    echo "  Building Docker images (this may take a few minutes)..."
    ${dc_cmd} -f "$compose_file" build

    echo "  Starting Docker services..."
    ${dc_cmd} -f "$compose_file" up -d

    echo "  Services started."
}

# ---------------------------------------------------------------------------
# Wait for PostgreSQL to accept connections
# ---------------------------------------------------------------------------

wait_for_postgres_ready() {
    local install_dir="$1"
    local compose_file="${install_dir}/docker-compose.beta.yml"
    local max_wait="${2:-90}"
    local interval=5
    local elapsed=0
    local dc_cmd
    dc_cmd="$(docker_compose_cmd)"

    echo "  Waiting for PostgreSQL to be ready (max ${max_wait}s)..."
    while [[ "$elapsed" -lt "$max_wait" ]]; do
        if ${dc_cmd} -f "$compose_file" exec -T postgres \
            pg_isready -U "${BETA_POSTGRES_USER}" -d "${BETA_POSTGRES_DB}" \
            &>/dev/null 2>&1; then
            echo "  PostgreSQL: ready"
            return 0
        fi
        sleep "$interval"
        elapsed=$((elapsed + interval))
        echo "  Still waiting... (${elapsed}s / ${max_wait}s)"
    done

    echo "  ERROR: PostgreSQL did not become ready within ${max_wait}s" >&2
    echo "  Check logs: docker compose -f ${compose_file} logs postgres" >&2
    return 1
}

# ---------------------------------------------------------------------------
# Wait for the app container to serve /api/health
# ---------------------------------------------------------------------------

wait_for_app_healthy() {
    local port="${1:-8085}"
    local max_attempts="${2:-24}"
    local interval=5
    local attempt=1
    local url="http://localhost:${port}/api/health"

    echo "  Waiting for application health endpoint (max $((max_attempts * interval))s)..."
    while [[ "$attempt" -le "$max_attempts" ]]; do
        if curl -sf --max-time 5 "$url" >/dev/null 2>&1; then
            echo "  Application: healthy"
            return 0
        fi
        sleep "$interval"
        echo "  Attempt ${attempt}/${max_attempts} — not yet responding..."
        attempt=$((attempt + 1))
    done

    echo "  ERROR: Application health endpoint did not respond after $((max_attempts * interval))s" >&2
    return 1
}

# ---------------------------------------------------------------------------
# Final health assertion — prints response and fails loudly on error
# ---------------------------------------------------------------------------

verify_health_endpoint() {
    local port="${1:-8085}"
    local url="http://localhost:${port}/api/health"

    echo "  Verifying health endpoint: ${url}"
    local response
    if ! response=$(curl -sf --max-time 10 "$url" 2>&1); then
        echo "  ERROR: Health endpoint returned an error:" >&2
        echo "  ${response}" >&2
        return 1
    fi

    echo "  Response: ${response}"
    if echo "$response" | grep -q '"status":"ok"'; then
        echo "  Health check: PASS"
        return 0
    else
        echo "  ERROR: Unexpected health response (expected status:ok)" >&2
        return 1
    fi
}
