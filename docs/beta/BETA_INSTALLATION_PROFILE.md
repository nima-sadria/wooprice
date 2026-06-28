# WooPrice Beta — Installation Profile

**Document:** BETA_INSTALLATION_PROFILE.md
**Series:** B6 Pre-Installation Reference
**Status:** DRAFT — awaiting B6 implementation review
**Last revised:** 2026-06-28

This document defines every runtime parameter, external dependency, secret,
and verification step required to install WooPrice Beta on a clean server.
It is the authoritative reference for B6 (Docker Runtime Foundation) and for
administrators performing a fresh installation.

No real credential values are recorded here. All examples use placeholder
notation: `<PLACEHOLDER>`.

---

## 1. Hardware Requirements

### 1.1 Minimum

Sufficient to run WooPrice Beta with a single integration and light load.
Not suitable for production workloads.

| Resource | Minimum |
|---|---|
| CPU | 1 vCPU (x86_64) |
| RAM | 2 GB |
| Disk | 20 GB (SSD preferred) |
| OS | Ubuntu 22.04 LTS / Debian 12 / RHEL 9 compatible |
| Docker Engine | 24.0 or later |
| Docker Compose | 2.20 or later (V2 plugin — not legacy V1) |

### 1.2 Recommended

Suitable for single-operator Beta use with standard Nextcloud and WooCommerce
integrations.

| Resource | Recommended |
|---|---|
| CPU | 2 vCPU |
| RAM | 4 GB |
| Disk | 50 GB SSD |
| OS | Ubuntu 22.04 LTS or Debian 12 |
| Docker Engine | 25.0 or later |
| Docker Compose | 2.24 or later |

### 1.3 Production-like

Suitable for an operator running live WooCommerce sync jobs with scheduling,
audit logs, backups, and plugin extensions active.

| Resource | Production-like |
|---|---|
| CPU | 4 vCPU |
| RAM | 8 GB |
| Disk | 100 GB SSD (separate volume for storage and backups recommended) |
| OS | Ubuntu 22.04 LTS (LTS releases only) |
| Docker Engine | Latest stable |
| Docker Compose | Latest stable V2 plugin |

**Storage note:** For production-like deployments, mount `BETA_STORAGE_PATH`
and `BETA_BACKUP_PATH` on a separate disk or volume from the OS disk. This
prevents OS disk exhaustion from affecting the application and simplifies
backup procedures.

---

## 2. Network Requirements

### 2.1 Static IP or Stable DNS Target

The server running WooPrice Beta must have either:
- A static public IP address, or
- A stable DHCP reservation that does not change across reboots.

If using a cloud provider, assign an Elastic IP / Floating IP to the instance.

### 2.2 Reverse Proxy

WooPrice Beta is designed to sit behind a reverse proxy (Nginx recommended).
The reverse proxy is responsible for:
- Terminating TLS (when `BETA_SSL_MODE=off` or `letsencrypt`)
- Forwarding requests to the Beta app container on the internal port
- Setting `X-Forwarded-For`, `X-Forwarded-Proto`, and `Host` headers

A minimal Nginx configuration block is shown below as a reference shape only.
Exact paths and port numbers depend on your `BETA_PORT` setting.

```
# Reference shape only — not a production-ready config
server {
    listen 443 ssl;
    server_name <BETA_DOMAIN>;

    location / {
        proxy_pass http://127.0.0.1:<BETA_PORT>;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 2.3 Ports

| Port | Direction | Purpose | Notes |
|---|---|---|---|
| 80 | Inbound | HTTP (redirect to 443) | Required for Let's Encrypt ACME challenge |
| 443 | Inbound | HTTPS | Public-facing entry point |
| `BETA_PORT` | Internal only | WooPrice Beta app | Default: 8000; must not be exposed externally |
| 5432 | Internal only | PostgreSQL | Never exposed externally |
| 6379 | Internal only | Redis (B6+) | Never exposed externally |

**Firewall rule summary:** Only ports 80 and 443 are exposed to the public
internet. All other ports are internal to the Docker network.

### 2.4 DNS

Before installation, create the following DNS A record:

```
<BETA_DOMAIN>  IN  A  <SERVER_PUBLIC_IP>
TTL: 300 (lower during initial setup; raise to 3600 once stable)
```

DNS propagation must be confirmed before running the installer if using
`BETA_SSL_MODE=letsencrypt` (Let's Encrypt requires a publicly resolvable
domain for ACME challenge).

Verify propagation with:
```
nslookup <BETA_DOMAIN>
dig +short <BETA_DOMAIN>
```

### 2.5 NTP

The server clock must be synchronized. WooPrice Beta uses UTC timestamps for:
- JWT token issuance and expiry verification
- Audit log timestamps
- Backup filenames
- Health check last-checked-at records

Recommended: `systemd-timesyncd` (enabled by default on Ubuntu 22.04) or
`chrony`. Verify with: `timedatectl status` — NTP service must show `active`.

### 2.6 Firewall

Recommended `ufw` rules (adjust for your provider's firewall):

```
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp     # SSH (restrict to your IP in production)
ufw allow 80/tcp     # HTTP / ACME challenge
ufw allow 443/tcp    # HTTPS
ufw enable
```

No other inbound ports should be opened. The Docker daemon manages its own
iptables rules for inter-container communication.

---

## 3. Required Domains

WooPrice Beta requires one domain or subdomain that points to the installation
server. The domain is set as `BETA_DOMAIN` in `.env`.

**Pattern:** `{prefix}.{base-domain}`

**Example (shape only — do not hardcode production values in this document):**

```
beta.woo.<your-domain>
```

### 3.1 Domain Requirements

| Requirement | Detail |
|---|---|
| DNS A record | Must resolve to the server's public IP before install |
| HTTPS | Required for production. Let's Encrypt or operator-provided cert. |
| Subdomain recommended | Isolates Beta from any existing services on the root domain |
| No trailing slash | `BETA_DOMAIN` must be a bare hostname, not a URL |
| No port in domain | Port is specified separately via `BETA_PORT` |

### 3.2 Subdomain Examples (shapes only)

| Pattern | Use case |
|---|---|
| `beta.woo.<domain>` | Standard Beta deployment |
| `woo-staging.<domain>` | Staging / pre-production |
| `woo-dev.<domain>` | Development server |

---

## 4. Nextcloud Requirements

WooPrice Beta reads the product price spreadsheet from Nextcloud via the
WebDAV API. A dedicated service account with an App Password is required.

### 4.1 Required User

| Requirement | Detail |
|---|---|
| Account type | Dedicated service account (not a personal login) |
| Username | Set as `BETA_NEXTCLOUD_USERNAME` in `.env` |
| Display name | Recommended: `WooPrice Beta` or similar |
| Quota | Sufficient to hold the price spreadsheet (typically < 100 MB) |

**Do not use a personal Nextcloud account.** If the personal account's
password changes, the integration breaks. A dedicated service account
can be managed independently.

### 4.2 App Password

WooPrice Beta authenticates to Nextcloud using a Nextcloud **App Password**,
not the account's login password.

**How to generate:**
1. Log in to Nextcloud as the service account.
2. Navigate to: Settings → Security → Devices & sessions.
3. Under "Create new app password", enter a name (e.g. `wooprice-beta`).
4. Copy the generated password immediately — it is shown only once.
5. Set as `BETA_NEXTCLOUD_PASSWORD` in `.env`.

App Passwords survive login password changes and can be revoked individually
without affecting the account.

### 4.3 Required Permissions

| Permission | Required | Purpose |
|---|---|---|
| Files — Read | Yes | Download the price spreadsheet |
| Files — WebDAV | Yes | API access method used by WooPrice |
| Files — Write | No | WooPrice Beta does not write to Nextcloud |
| Sharing | No | Not required |
| Admin access | No | Not required |

### 4.4 Spreadsheet Location

The price spreadsheet must be:
- Uploaded to the service account's Nextcloud Files folder
- At the path set as `BETA_NEXTCLOUD_FILE_PATH`
- In `.xlsx` (Excel Open XML) format
- Accessible to the service account without shared link or external token

**Example `BETA_NEXTCLOUD_FILE_PATH` value (shape only):**
```
/WooPrice/<filename>.xlsx
```

The path is relative to the service account's home directory on the
Nextcloud server.

### 4.5 Folder Permissions

The parent folder containing the spreadsheet must be:
- Owned by the service account, or shared to the service account with
  at least Read permission.
- Not hidden or excluded by Nextcloud server rules.

### 4.6 WebDAV Requirements

| Requirement | Detail |
|---|---|
| WebDAV endpoint | `https://<nextcloud-host>/remote.php/dav/files/<username>/` |
| Protocol | HTTPS required in production |
| Authentication | HTTP Basic auth (App Password) |
| TLS | Server certificate must be valid and trusted (not self-signed in production) |
| Connection | Must be reachable from the WooPrice Beta server |

Set `BETA_NEXTCLOUD_URL` to the Nextcloud root URL (without WebDAV path):
```
BETA_NEXTCLOUD_URL=https://<nextcloud-host>
```

The installer constructs the WebDAV URL from `BETA_NEXTCLOUD_URL` and
`BETA_NEXTCLOUD_USERNAME` at runtime.

---

## 5. WooCommerce Requirements

WooPrice Beta writes product prices to WooCommerce via the WooCommerce
REST API v3.

### 5.1 REST API Requirements

| Requirement | Detail |
|---|---|
| WooCommerce version | 6.0 or later (REST API v3) |
| WordPress version | 6.0 or later |
| Permalink structure | Must not be "Plain" — requires Pretty Permalinks |
| REST API enabled | Enabled by default; confirm at WooCommerce → Settings → Advanced → REST API |

### 5.2 Credentials

WooCommerce REST API credentials are generated in the WooCommerce admin panel:

**Path:** WooCommerce → Settings → Advanced → REST API → Add Key

| Field | Value |
|---|---|
| Description | `WooPrice Beta` (or similar) |
| User | A WordPress administrator account |
| Permissions | Read/Write (see §5.3) |

After generating, copy:
- **Consumer Key** → `BETA_WOOCOMMERCE_KEY`
- **Consumer Secret** → `BETA_WOOCOMMERCE_SECRET`

These are shown once. Store them immediately in `.env`.

### 5.3 Permissions

| Permission level | Use case | Note |
|---|---|---|
| Read | Health checks, diagnostics only | Sufficient for `wooprice health woocommerce` |
| Read/Write | Full price sync operations | Required for execution phase |

**Recommended:** Use Read/Write for the installation. A Read-only diagnostic
key is not required as a separate credential — the health check uses the same
key with a lightweight read-only API call.

### 5.4 SSL Requirements

| Requirement | Detail |
|---|---|
| WooCommerce HTTPS | Required in production. REST API requests to a non-HTTPS endpoint are rejected by WooPrice Beta's security policy. |
| Certificate validity | Server certificate must be valid and trusted by the WooPrice Beta server's system certificate store |
| Self-signed certs | Not permitted in production. Use a CA-signed or Let's Encrypt certificate on the WooCommerce host. |

Set `BETA_WOOCOMMERCE_URL` to the HTTPS root of the WooCommerce store:
```
BETA_WOOCOMMERCE_URL=https://<woocommerce-host>
```

---

## 6. Generated Secrets

All secrets listed below are generated by `wooprice install` or must be
provided by the operator before installation. No secret is hardcoded in
the application.

### 6.1 Secret Inventory

| Secret | Env var | Minimum length | Generator | Storage |
|---|---|---|---|---|
| JWT signing secret | `BETA_JWT_SECRET` | 64 characters | `openssl rand -hex 64` | `.env` only |
| REST API internal secret | `BETA_REST_API_SECRET` | 32 characters | `openssl rand -hex 32` | `.env` only |
| PostgreSQL password | `BETA_POSTGRES_PASSWORD` | 24 characters | `openssl rand -base64 18` | `.env` only |
| Nextcloud App Password | `BETA_NEXTCLOUD_PASSWORD` | (set by Nextcloud) | Nextcloud App Password generator | `.env` only |
| WooCommerce Consumer Key | `BETA_WOOCOMMERCE_KEY` | (set by WooCommerce) | WooCommerce REST API panel | `.env` only |
| WooCommerce Consumer Secret | `BETA_WOOCOMMERCE_SECRET` | (set by WooCommerce) | WooCommerce REST API panel | `.env` only |

### 6.2 Generation Commands

```bash
# JWT signing secret (64 hex chars = 256-bit entropy)
openssl rand -hex 64

# REST API internal secret (32 hex chars = 128-bit entropy)
openssl rand -hex 32

# PostgreSQL password (24 base64 chars ≈ 144-bit entropy)
openssl rand -base64 18
```

The installer (`wooprice install`) generates `BETA_JWT_SECRET`,
`BETA_REST_API_SECRET`, and `BETA_POSTGRES_PASSWORD` automatically if they
are not already set in `.env`. Operator-owned secrets (`NEXTCLOUD_PASSWORD`,
`WOOCOMMERCE_KEY`, `WOOCOMMERCE_SECRET`) must be provided before installation.

### 6.3 Rotation Policy

| Secret | Rotation trigger | Rotation method |
|---|---|---|
| `BETA_JWT_SECRET` | Suspected compromise; annual at minimum | Update `.env`, restart app container; all existing sessions are invalidated |
| `BETA_REST_API_SECRET` | Suspected compromise | Update `.env`, restart app container |
| `BETA_POSTGRES_PASSWORD` | Suspected compromise; DBA policy | Update `.env` and database user simultaneously; restart db and app containers |
| `BETA_NEXTCLOUD_PASSWORD` | Account credential change; compromise | Revoke old App Password in Nextcloud, generate new one, update `.env` |
| `BETA_WOOCOMMERCE_KEY/SECRET` | WooCommerce admin policy; compromise | Revoke key in WooCommerce REST API panel, generate new key, update `.env` |

**Identity fields (`BETA_NEXTCLOUD_USERNAME`) are not rotated** — they are
`.env`-only and changing them requires a new Nextcloud account setup.

### 6.4 Secret Handling Rules

- Secrets are never logged at any log level.
- Secrets are never included in API responses, diagnostic reports, or audit records.
- The `.env` file must not be committed to version control.
- File permissions on `.env`: `600` (owner read/write only).
- The `BETA_JWT_SECRET` minimum of 64 characters is enforced by the schema validator.
- The `BETA_REST_API_SECRET` minimum of 32 characters is enforced by the schema validator.

---

## 7. Storage Layout

WooPrice Beta uses two configurable root paths: `BETA_STORAGE_PATH` and
`BETA_BACKUP_PATH`. Both must exist before installation and must be writable
by the user running Docker containers.

### 7.1 Primary Storage (`BETA_STORAGE_PATH`)

```
$BETA_STORAGE_PATH/
├── plugins/            ← Plugin installations (BETA_PLUGIN_DIR; auto-computed)
│   └── <plugin-name>/  ← Each plugin in its own subdirectory
├── config/             ← Runtime configuration overrides (CP1.3+)
│   └── runtime.toml    ← Operator-editable integration endpoints and timeouts
├── cache/              ← In-memory cache spillover (B6+; currently in-memory only)
└── locks/              ← Advisory lock files for scheduled jobs
```

### 7.2 Backup Storage (`BETA_BACKUP_PATH`)

```
$BETA_BACKUP_PATH/
└── <YYYY-MM-DD>/       ← One directory per backup date
    ├── db.dump         ← PostgreSQL pg_dump output
    ├── config.tar.gz   ← Compressed snapshot of $BETA_STORAGE_PATH/config/
    └── manifest.json   ← Backup metadata: timestamp, version, checksum
```

Backup retention is controlled by `BETA_BACKUP_RETAIN_DAYS` (default: 30).
Backups older than the retention window are deleted automatically.

### 7.3 Logs

Log output is captured by Docker and routed via the configured log driver.
Default: `json-file` with rotation.

| Stream | Location |
|---|---|
| Application logs | `docker compose logs app` |
| Worker logs | `docker compose logs worker` |
| Database logs | `docker compose logs db` |
| Nginx logs | `docker compose logs nginx` |
| Audit trail | `$BETA_STORAGE_PATH/config/audit.jsonl` (CP1.3+) |

### 7.4 Ownership and Permissions

| Path | Owner | Mode |
|---|---|---|
| `$BETA_STORAGE_PATH` | Docker container user (uid 1000 recommended) | `755` |
| `$BETA_STORAGE_PATH/plugins/` | Docker container user | `755` |
| `$BETA_STORAGE_PATH/config/` | Docker container user | `700` |
| `$BETA_BACKUP_PATH` | Docker container user | `755` |
| `.env` | Server operator user | `600` |

---

## 8. SSL Modes

Set via `BETA_SSL_MODE` in `.env`. Valid values: `off`, `letsencrypt`,
`manual`, `self-signed`.

### 8.1 `off` — Reverse Proxy Handles TLS (Recommended)

The application receives plain HTTP. TLS is terminated externally by Nginx
(or another reverse proxy) before requests reach the app container.

**Use when:** Nginx or another proxy with Let's Encrypt or an operator-managed
certificate sits in front of the application.

| Property | Detail |
|---|---|
| App port | `BETA_PORT` receives plain HTTP from the proxy |
| TLS cert | Managed by the reverse proxy (e.g., Certbot / Let's Encrypt) |
| External traffic | Always HTTPS (proxy enforces redirect from 80 → 443) |
| `X-Forwarded-Proto` | Must be set to `https` by the proxy |
| Production suitability | Yes |

### 8.2 `letsencrypt` — Automatic Let's Encrypt

The application or a companion container (Certbot/ACME) obtains and renews
a Let's Encrypt certificate automatically.

**Use when:** The server has a public DNS entry and port 80 is reachable for
the ACME HTTP-01 challenge.

| Property | Detail |
|---|---|
| DNS requirement | Domain must be publicly resolvable before installation |
| Port 80 | Must be open during initial certificate issuance and renewal |
| Auto-renewal | Handled by the companion container or cron hook |
| Rate limits | Let's Encrypt: 5 certificates per domain per week |
| Production suitability | Yes |

### 8.3 `manual` — Operator-Provided Certificate

The operator supplies certificate and private key files. WooPrice Beta
mounts them into the Nginx container.

**Use when:** A corporate CA or wildcard certificate is in use.

| Property | Detail |
|---|---|
| Certificate file | PEM format; full chain preferred |
| Key file | PEM format; no passphrase (or passphrase must be removed before use) |
| Renewal | Operator responsibility |
| Production suitability | Yes |

### 8.4 `self-signed` — Self-Signed Certificate

A self-signed certificate is auto-generated at startup. The certificate is
not trusted by browsers or external services without manual trust configuration.

**Use when:** Local development, CI environments, or air-gapped testing where
browser trust is not required.

| Property | Detail |
|---|---|
| Trust | Not trusted by browsers or Nextcloud/WooCommerce servers by default |
| Nextcloud integration | Will fail TLS check unless Nextcloud is configured to trust the cert |
| Production suitability | No |

---

## 9. Installation Checklist

Everything the administrator must prepare **before** running `wooprice install`.

### 9.1 Server

- [ ] Server provisioned with at minimum 2 GB RAM and 20 GB disk
- [ ] OS: Ubuntu 22.04 LTS or Debian 12 installed and updated
  ```
  apt update && apt upgrade -y
  ```
- [ ] Docker Engine 24.0+ installed
  ```
  docker --version    # must show 24.x or later
  ```
- [ ] Docker Compose V2 plugin installed
  ```
  docker compose version    # must show 2.20 or later; not docker-compose (V1)
  ```
- [ ] NTP synchronized
  ```
  timedatectl status    # NTP service: active; System clock synchronized: yes
  ```
- [ ] Firewall configured: only ports 22, 80, 443 inbound

### 9.2 Network and DNS

- [ ] Static IP assigned to the server
- [ ] DNS A record created: `<BETA_DOMAIN>` → `<SERVER_IP>`
- [ ] DNS propagated and resolvable from the server
  ```
  nslookup <BETA_DOMAIN>
  ```
- [ ] Reverse proxy configured (if `BETA_SSL_MODE=off`)
- [ ] SSL certificate provisioned or Let's Encrypt plan confirmed

### 9.3 Nextcloud

- [ ] Dedicated Nextcloud service account created
- [ ] Nextcloud App Password generated and stored
- [ ] Price spreadsheet (`.xlsx`) uploaded to Nextcloud at the target path
- [ ] Service account has read access to the spreadsheet
- [ ] WebDAV endpoint reachable from the server
  ```
  curl -u <USERNAME>:<APP_PASSWORD> https://<nextcloud-host>/remote.php/dav/files/<USERNAME>/
  ```

### 9.4 WooCommerce

- [ ] WooCommerce REST API enabled
- [ ] Pretty Permalinks enabled in WordPress
- [ ] Consumer Key and Consumer Secret generated (Read/Write)
- [ ] WooCommerce store reachable from the server over HTTPS
  ```
  curl https://<woocommerce-host>/wp-json/wc/v3/system_status
  ```

### 9.5 Storage Paths

- [ ] `BETA_STORAGE_PATH` directory created
  ```
  mkdir -p <BETA_STORAGE_PATH>
  ```
- [ ] `BETA_BACKUP_PATH` directory created
  ```
  mkdir -p <BETA_BACKUP_PATH>
  ```
- [ ] Both paths writable by the Docker container user

### 9.6 Secrets

- [ ] `BETA_JWT_SECRET` generated (min 64 chars)
- [ ] `BETA_REST_API_SECRET` generated (min 32 chars)
- [ ] `BETA_POSTGRES_PASSWORD` generated (min 24 chars)
- [ ] All operator secrets gathered: Nextcloud App Password, WooCommerce key/secret

### 9.7 Environment File

- [ ] `.env` file created at the project root
- [ ] All 22 required `BETA_*` variables populated (see §6 and validation.py `REQUIRED_FIELDS`)
- [ ] `.env` permissions set to `600`
  ```
  chmod 600 .env
  ```
- [ ] `.env` is in `.gitignore` (verified — never commit secrets)
- [ ] Configuration verified before install
  ```
  wooprice configure verify
  ```

---

## 10. Verification Checklist

Everything to confirm **after** `wooprice install` completes successfully.

### 10.1 API

- [ ] Public health endpoint returns 200
  ```
  curl https://<BETA_DOMAIN>/api/health
  # Expected: {"status": "available"}
  ```
- [ ] Full health endpoint returns 200 (requires auth token)
  ```
  curl -H "Authorization: Bearer <TOKEN>" https://<BETA_DOMAIN>/api/v2/health
  ```

### 10.2 CLI

- [ ] CLI version reports correctly
  ```
  wooprice --version
  ```
- [ ] CLI config shows current values (no validation errors)
  ```
  wooprice configure show
  ```

### 10.3 Health

- [ ] All health checks green
  ```
  wooprice health all
  ```
- [ ] Per-service checks individually green
  ```
  wooprice health nextcloud
  wooprice health woocommerce
  wooprice health database
  wooprice health storage
  ```

### 10.4 Diagnostics

- [ ] Diagnostics run with no CRITICAL findings
  ```
  wooprice diagnostics run
  ```
- [ ] No BLOCKER or HIGH severity findings unresolved

### 10.5 Configuration

- [ ] Configuration verified without errors
  ```
  wooprice configure verify
  ```
- [ ] `BETA_DOMAIN`, `BETA_PORT`, `BETA_SSL_MODE` reflect the installed values
- [ ] `BETA_ENV` is set to `beta` or `production` (not `dev`) on a live server

### 10.6 Storage

- [ ] Storage path exists and is writable
  ```
  wooprice health storage
  ```
- [ ] Backup path exists and is writable
- [ ] Plugin directory exists (auto-created as `$BETA_STORAGE_PATH/plugins/`)

### 10.7 Nextcloud

- [ ] Nextcloud connection check passes
  ```
  wooprice health nextcloud
  ```
- [ ] Spreadsheet file discovered at `BETA_NEXTCLOUD_FILE_PATH`
- [ ] Failure class reported as `none` (not `dns_failure`, `tls_failure`, or `unauthorized`)

### 10.8 WooCommerce

- [ ] WooCommerce connection check passes
  ```
  wooprice health woocommerce
  ```
- [ ] Product count returns a non-zero value
- [ ] Failure class reported as `none`

---

## Appendix A — Required Environment Variables Reference

The following table lists all variables from `app/beta/config/validation.py`.
Variables marked Required must be present in `.env` before the installer
will proceed.

| Variable | Required | Default | Description |
|---|---|---|---|
| `BETA_ENV` | Yes | — | Deployment profile: `dev`, `beta`, `production` |
| `BETA_DOMAIN` | Yes | — | Hostname where Beta is served (no protocol, no port) |
| `BETA_PORT` | Yes | — | Application server port (1024–65535) |
| `BETA_SSL_MODE` | Yes | — | TLS mode: `off`, `letsencrypt`, `manual`, `self-signed` |
| `BETA_DATABASE_URL` | Yes | — | Full PostgreSQL connection URL |
| `BETA_POSTGRES_DB` | Yes | — | PostgreSQL database name |
| `BETA_POSTGRES_USER` | Yes | — | PostgreSQL username |
| `BETA_POSTGRES_PASSWORD` | Yes | — | PostgreSQL password (secret) |
| `BETA_JWT_SECRET` | Yes | — | JWT signing key — minimum 64 characters |
| `BETA_REST_API_SECRET` | Yes | — | Internal REST API secret — minimum 32 characters |
| `BETA_NEXTCLOUD_URL` | Yes | — | Nextcloud root URL (`https://…`) |
| `BETA_NEXTCLOUD_FILE_PATH` | Yes | — | Path to spreadsheet within Nextcloud |
| `BETA_NEXTCLOUD_USERNAME` | Yes | — | Nextcloud service account username |
| `BETA_NEXTCLOUD_PASSWORD` | Yes | — | Nextcloud App Password (secret) |
| `BETA_WOOCOMMERCE_URL` | Yes | — | WooCommerce store root URL (`https://…`) |
| `BETA_WOOCOMMERCE_KEY` | Yes | — | WooCommerce Consumer Key (secret) |
| `BETA_WOOCOMMERCE_SECRET` | Yes | — | WooCommerce Consumer Secret (secret) |
| `BETA_TIMEZONE` | Yes | — | IANA timezone string (e.g. `Europe/Amsterdam`) |
| `BETA_CURRENCY` | Yes | — | 3-letter ISO 4217 currency code (e.g. `EUR`) |
| `BETA_ADMIN_EMAIL` | Yes | — | Administrator email address |
| `BETA_STORAGE_PATH` | Yes | — | Absolute path for application storage |
| `BETA_BACKUP_PATH` | Yes | — | Absolute path for backup storage |
| `BETA_LOG_LEVEL` | No | `INFO` | Log verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `BETA_JWT_ACCESS_TTL_MINUTES` | No | `15` | Access token lifetime in minutes |
| `BETA_JWT_REFRESH_TTL_DAYS` | No | `7` | Refresh token lifetime in days |
| `BETA_MAX_UPLOAD_MB` | No | `50` | Maximum file upload size in MB |
| `BETA_WORKER_CONCURRENCY` | No | `2` | Number of parallel worker threads |
| `BETA_SCHEDULER_POLL_SECONDS` | No | `30` | Scheduler polling interval in seconds |
| `BETA_BACKUP_RETAIN_DAYS` | No | `30` | Number of days to retain backups |
| `BETA_PLUGIN_DIR` | No | `$BETA_STORAGE_PATH/plugins` | Plugin installation directory (auto-computed if absent) |
