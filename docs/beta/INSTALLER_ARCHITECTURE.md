# WooPrice Beta — Installer Architecture

**Document:** INSTALLER_ARCHITECTURE.md
**Series:** B1 Architecture Blueprint
**B4 implementation note (2026-06-27):** Installer Foundation implemented.
Python core (`installer/installer_core.py`) provides all testable business logic:
prerequisite checks, secret generation, .env generation, TOML config generation,
storage setup, dry-run mode, rollback, and B3 validation integration.
Bash scripts (`install.sh`, `lib/`) are the Linux deployment entry point.
Steps 8–13 (Docker launch, DB init, admin, SSL, health check) are NOT in B4 scope.
B4 does NOT deploy to production. B4 does NOT start Docker services.

---

## Overview

The WooPrice Beta installer is a self-contained Bash script that sets up a complete,
isolated Beta environment on a clean Linux server. It requires no prior knowledge of
Docker or Python — the wizard collects all configuration values, validates them, and
generates all required artifacts.

---

## Installation Flow

```
install.sh
    │
    ├── 1. Prerequisite Checks
    │       Check OS, Docker, Docker Compose, disk space, ports, openssl
    │
    ├── 2. Welcome Banner
    │       Display WooPrice Beta version, environment, isolation warning
    │
    ├── 3. Interactive Wizard (12 sections)
    │       Collect all BETA_* configuration values
    │
    ├── 4. Secret Generation
    │       Generate BETA_JWT_SECRET, BETA_REST_API_SECRET, BETA_POSTGRES_PASSWORD
    │       (unless user supplied their own)
    │
    ├── 5. .env File Generation
    │       Write all collected and generated values to .env
    │
    ├── 6. Docker Compose Generation
    │       Substitute placeholders in docker-compose.template.yml
    │       Write docker-compose.beta.yml
    │
    ├── 7. Storage Directory Setup
    │       Create BETA_STORAGE_PATH and BETA_BACKUP_PATH structures
    │
    ├── 8. Stack Launch
    │       docker compose -f docker-compose.beta.yml up -d
    │
    ├── 9. Database Initialization
    │       Wait for PostgreSQL to be healthy
    │       Run: wooprice migrate up (A2 + Beta migrations)
    │
    ├── 10. Admin Account Creation
    │       Create initial admin user via API
    │       Print credentials to terminal (one time only)
    │
    ├── 11. SSL Setup
    │       Apply SSL mode: off / self-signed / letsencrypt / manual
    │
    ├── 12. Health Check
    │       Run: wooprice health all
    │       Confirm all services healthy
    │
    └── 13. Completion Report
            Write install.log
            Print summary to terminal
            Print first-login URL (BETA_DOMAIN:BETA_PORT)
```

---

## 1. Prerequisite Checks (`lib/checks.sh`)

The installer checks the following before proceeding. Each check reports PASS or FAIL
with a clear remediation instruction.

| Check | Required version / condition |
|---|---|
| OS | Linux (Debian/Ubuntu/RHEL/CentOS/Arch) |
| Docker | >= 24.0 |
| Docker Compose | >= 2.20 (plugin form) |
| Available disk | >= 5 GB at `$INSTALL_DIR` |
| Available disk (backup) | >= 10 GB at `$BACKUP_DIR` |
| Port available | `BETA_PORT` not in use |
| Port available | PostgreSQL port (5432 by default) not in use by other service |
| `openssl` | Available in PATH |
| `curl` | Available in PATH |
| Internet access | Reachable (for image pull) |
| Write permission | `$INSTALL_DIR` must be writable by current user |

If any check fails, the installer prints the specific fix and exits. No partial state
is written on prerequisite failure.

---

## 2. Welcome Banner

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  WooPrice Beta Installer  v1.0.0
  [BETA ENVIRONMENT — NOT PRODUCTION]

  This installer sets up a completely isolated Beta environment.
  It will NOT modify any Production WooPrice installation.

  All configuration is collected interactively.
  No manual file editing is required.

  Prerequisites: PASS (all checks passed)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 3. Interactive Wizard (`lib/wizard.sh`)

The wizard is organized into 12 sections. Each section is displayed one at a time.
Questions within a section appear sequentially. The user may press Ctrl+C at any
point to abort (no partial state is written until Section 5).

### Wizard sections

**Section 1 — Network**
- Beta domain (BETA_DOMAIN) — no default; user must enter
- Beta port (BETA_PORT) — default: 8080
- SSL mode selection (BETA_SSL_MODE) — menu: off / self-signed / letsencrypt / manual

**Section 2 — Database**
- PostgreSQL database name (BETA_POSTGRES_DB) — default: wooprice_beta
- PostgreSQL username (BETA_POSTGRES_USER) — default: wooprice_beta
- PostgreSQL password (BETA_POSTGRES_PASSWORD) — offer to generate (recommended)
  or user-supplied (must be >= 20 chars)

**Section 3 — Secrets**
- JWT secret (BETA_JWT_SECRET) — offer to generate (recommended; 64+ chars)
- REST API secret (BETA_REST_API_SECRET) — offer to generate (recommended)

**Section 4 — Source**
- Source type selection: Nextcloud / CSV / Excel / Direct DB / API
- (If Nextcloud) Nextcloud URL (BETA_NEXTCLOUD_URL)
- (If Nextcloud) Spreadsheet path (BETA_NEXTCLOUD_FILE_PATH)
- (If Nextcloud) Username (BETA_NEXTCLOUD_USERNAME)
- (If Nextcloud) Password (BETA_NEXTCLOUD_PASSWORD) — input masked

**Section 5 — WooCommerce**
- WooCommerce store URL (BETA_WOOCOMMERCE_URL) — test store only
- WooCommerce consumer key (BETA_WOOCOMMERCE_KEY) — input masked
- WooCommerce consumer secret (BETA_WOOCOMMERCE_SECRET) — input masked

**Section 6 — Environment**
- Timezone (BETA_TIMEZONE) — default: UTC; searchable list
- Default currency (BETA_CURRENCY) — default: USD; selectable list

**Section 7 — Admin Account**
- Admin email (BETA_ADMIN_EMAIL)
- Initial admin password — input masked; must be >= 12 chars; displayed once on completion

**Section 8 — Storage**
- Storage base path (BETA_STORAGE_PATH) — default: `/opt/wooprice-beta/storage`
- Backup path (BETA_BACKUP_PATH) — default: `/opt/wooprice-beta/backups`

**Section 9 — Confirmation**
- Display summary of all collected values (secrets masked)
- Prompt: "Proceed with installation? [Y/n]"
- If N: abort without writing any files

**Sections 10–12** are handled by subsequent installer stages (generation, setup, launch).

---

## 4. Secret Generation (`lib/secrets.sh`)

```bash
generate_secret() {
    local length="${1:-64}"
    openssl rand -base64 "$length" | tr -d '\n'
}

generate_hex_secret() {
    local bytes="${1:-32}"
    openssl rand -hex "$bytes"
}
```

Secrets are held in shell variables only. They are written once to the `.env` file
(Section 5) and are never echoed to the terminal as plain text after that point.

---

## 5. `.env` File Generation (`lib/env_gen.sh`)

```bash
generate_env_file() {
    local env_path="$INSTALL_DIR/.env"
    cat > "$env_path" <<ENVFILE
# WooPrice Beta — generated environment file
# Created: $(date -u +%Y-%m-%dT%H:%M:%SZ)
# DO NOT COMMIT THIS FILE

BETA_ENV=beta
BETA_DOMAIN=${BETA_DOMAIN}
BETA_PORT=${BETA_PORT}
BETA_DATABASE_URL=postgresql://${BETA_POSTGRES_USER}:${BETA_POSTGRES_PASSWORD}@postgres:5432/${BETA_POSTGRES_DB}
BETA_POSTGRES_DB=${BETA_POSTGRES_DB}
BETA_POSTGRES_USER=${BETA_POSTGRES_USER}
BETA_POSTGRES_PASSWORD=${BETA_POSTGRES_PASSWORD}
BETA_JWT_SECRET=${BETA_JWT_SECRET}
BETA_REST_API_SECRET=${BETA_REST_API_SECRET}
BETA_NEXTCLOUD_URL=${BETA_NEXTCLOUD_URL}
BETA_NEXTCLOUD_FILE_PATH=${BETA_NEXTCLOUD_FILE_PATH}
BETA_NEXTCLOUD_USERNAME=${BETA_NEXTCLOUD_USERNAME}
BETA_NEXTCLOUD_PASSWORD=${BETA_NEXTCLOUD_PASSWORD}
BETA_WOOCOMMERCE_URL=${BETA_WOOCOMMERCE_URL}
BETA_WOOCOMMERCE_KEY=${BETA_WOOCOMMERCE_KEY}
BETA_WOOCOMMERCE_SECRET=${BETA_WOOCOMMERCE_SECRET}
BETA_TIMEZONE=${BETA_TIMEZONE}
BETA_CURRENCY=${BETA_CURRENCY}
BETA_ADMIN_EMAIL=${BETA_ADMIN_EMAIL}
BETA_STORAGE_PATH=${BETA_STORAGE_PATH}
BETA_BACKUP_PATH=${BETA_BACKUP_PATH}
BETA_SSL_MODE=${BETA_SSL_MODE}
ENVFILE
    chmod 600 "$env_path"
}
```

The `.env` file is owned by the installing user with mode `600` (owner read/write only).

---

## 6. Docker Compose Generation (`lib/compose_gen.sh`)

The Docker Compose file is generated by substituting placeholders in
`installer/templates/docker-compose.template.yml`. Substitution uses `envsubst`
(from the `gettext` package). The output is written to `$INSTALL_DIR/docker-compose.beta.yml`.

The template contains only placeholders matching the `BETA_*` variable names.
No real values appear in the template or the generated file (the generated file
contains the substituted values from `.env`).

---

## 7. Storage Directory Setup (`lib/storage.sh`)

```bash
setup_storage() {
    mkdir -p \
        "${BETA_STORAGE_PATH}/logs" \
        "${BETA_STORAGE_PATH}/config" \
        "${BETA_STORAGE_PATH}/plugins" \
        "${BETA_STORAGE_PATH}/uploads" \
        "${BETA_STORAGE_PATH}/diagnostics" \
        "${BETA_BACKUP_PATH}"
    
    chown -R "$(whoami)" "${BETA_STORAGE_PATH}" "${BETA_BACKUP_PATH}"
    chmod -R 750 "${BETA_STORAGE_PATH}" "${BETA_BACKUP_PATH}"
}
```

---

## 8. SSL Setup (`lib/ssl.sh`)

| Mode | Action |
|---|---|
| `off` | No SSL configuration. HTTP only. |
| `self-signed` | Generate self-signed certificate using `openssl req`. Write to `BETA_STORAGE_PATH/ssl/`. Configure Nginx to use it. |
| `letsencrypt` | Use Certbot in a container. Requires `BETA_DOMAIN` to be DNS-resolvable. |
| `manual` | Prompt user for certificate path and key path. Copy to `BETA_STORAGE_PATH/ssl/`. |

---

## 9. Rollback on Failed Install

If any step from 6 onward fails:

1. Print a clear error identifying the failed step
2. Attempt to stop any started containers (`docker compose down`)
3. Preserve the `.env` file (to allow diagnosis)
4. Print: "Installation failed at step N. To retry: re-run install.sh"
5. Write failure details to `$INSTALL_DIR/install-failure.log`

The installer does **not** delete the `.env` file or storage directories on failure —
these may be needed for diagnosis. The operator can delete them manually or run
`install.sh --clean` to remove partial state before retrying.

---

## 10. Admin Account Creation

After migrations complete, the installer creates the initial admin account by calling
the API directly:

```bash
create_admin() {
    local response
    response=$(curl -s -X POST \
        "http://localhost:${BETA_PORT}/api/v2/users/bootstrap-admin" \
        -H "X-API-Key: ${BETA_REST_API_SECRET}" \
        -H "Content-Type: application/json" \
        -d "{\"email\": \"${BETA_ADMIN_EMAIL}\", \"password\": \"${ADMIN_INITIAL_PASSWORD}\"}")
    
    echo "Admin account created: ${BETA_ADMIN_EMAIL}"
    echo "Initial password: ${ADMIN_INITIAL_PASSWORD}"
    echo "(Change this password immediately after first login)"
}
```

The initial password is printed **once** to the terminal and also written to the
install log (`$BETA_STORAGE_PATH/install.log`) with a SENSITIVE marker. The install
log is mode `600`. The password is one-time and must be changed on first login.

---

## 11. Reinstall / Update Behavior

The installer detects if a previous installation exists at `$INSTALL_DIR`:

- **Fresh install:** proceeds normally.
- **Existing install (same version):** warns and offers: (a) skip to update, (b) reset
  config (data preserved), (c) full reinstall (data lost — requires explicit confirmation).
- **Existing install (different version):** recommends `wooprice update` instead of
  re-running the installer.

**Re-running the installer never silently overwrites an existing `.env` file** — it
always shows the existing values and asks for confirmation before overwriting.

---

## Completion Report

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  WooPrice Beta — Installation Complete  ✓
  [BETA ENVIRONMENT]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Application:  http(s)://BETA_DOMAIN:BETA_PORT
  Admin email:  BETA_ADMIN_EMAIL
  Install log:  BETA_STORAGE_PATH/install.log
  Config:       BETA_STORAGE_PATH/config/wooprice-beta.toml

  Next steps:
  1. Log in at: http(s)://BETA_DOMAIN:BETA_PORT
  2. Change your admin password immediately
  3. Run: wooprice health all
  4. Configure your source: wooprice sources add
  5. Test your WooCommerce channel: wooprice channels test

  This is a [BETA] environment.
  Do not use real customer data or the real WooCommerce store.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```
