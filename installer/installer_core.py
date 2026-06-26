"""WooPrice Beta — Installer Core (B4 Foundation)

Python implementation of the installer business logic.
Consumed by Bash entry point (install.sh) and tested directly by
tests/beta/installer/.

Design principles:
- Zero Docker execution, zero network calls, zero subprocess calls
- All validation delegates to B3 Configuration Foundation
- No A2 Platform Core imports — one-way dependency rule
- No hardcoded real domains, credentials, or production values
- Rollback tracks only what was created; never deletes pre-existing paths
"""

import os
import secrets
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.beta.config import ConfigValidator, ValidationResult

# Storage subdirectories created under BETA_STORAGE_PATH
_STORAGE_SUBDIRS: tuple[str, ...] = (
    "logs",
    "config",
    "plugins",
    "uploads",
    "diagnostics",
)

# Minimum secret lengths (mirrors B3 validation rules)
_JWT_SECRET_MIN_BYTES: int = 64
_REST_SECRET_HEX_BYTES: int = 32   # produces 64-char hex string
_PG_PASSWORD_BYTES: int = 24        # produces ~32-char urlsafe string


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class InstallerConfig:
    """All configuration values collected by the installer wizard.

    Fields with empty defaults must be supplied before file generation.
    Fields with non-empty defaults are optional and carry sensible values.
    """

    # --- Required (no usable default) ---
    domain: str = ""
    admin_email: str = ""
    nextcloud_url: str = ""
    nextcloud_file_path: str = ""
    nextcloud_username: str = ""
    nextcloud_password: str = ""
    woocommerce_url: str = ""
    woocommerce_key: str = ""
    woocommerce_secret: str = ""

    # --- With defaults ---
    env: str = "beta"
    port: int = 8080
    ssl_mode: str = "off"
    postgres_db: str = "wooprice_beta"
    postgres_user: str = "wooprice_beta"
    postgres_password: str = ""   # empty → auto-generate
    jwt_secret: str = ""           # empty → auto-generate
    rest_api_secret: str = ""      # empty → auto-generate
    timezone: str = "UTC"
    currency: str = "USD"
    storage_path: str = "/opt/wooprice-beta/storage"
    backup_path: str = "/opt/wooprice-beta/backups"
    log_level: str = "INFO"

    def needs_secret_generation(self) -> bool:
        return not self.jwt_secret or not self.rest_api_secret or not self.postgres_password


@dataclass
class InstallerSecrets:
    """Generated secrets.

    These are NEVER printed as plain text after creation.
    Display only via masked_summary().
    """

    jwt_secret: str
    rest_api_secret: str
    postgres_password: str

    def masked_summary(self) -> dict[str, str]:
        """Last-4 chars visible; rest is asterisks."""

        def _mask(s: str) -> str:
            return ("*" * 8 + s[-4:]) if len(s) > 4 else "****"

        return {
            "jwt_secret": _mask(self.jwt_secret),
            "rest_api_secret": _mask(self.rest_api_secret),
            "postgres_password": _mask(self.postgres_password),
        }


@dataclass
class PrerequisiteResult:
    """Result of a single prerequisite check."""

    name: str
    passed: bool
    message: str
    fix: str = ""

    def format_line(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        line = f"  [{status}] {self.name}: {self.message}"
        if not self.passed and self.fix:
            line += f"\n         Fix: {self.fix}"
        return line


@dataclass
class DryRunResult:
    """What the installer would do — produced without writing any files."""

    prerequisites: list[PrerequisiteResult]
    env_content: str
    toml_content: str
    storage_dirs: list[Path]
    secrets_would_be_generated: bool
    files_would_be_written: list[Path]

    @property
    def all_prerequisites_passed(self) -> bool:
        return all(r.passed for r in self.prerequisites)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InstallationCancelled(Exception):
    """Raised when the user declines the confirmation prompt."""


class InstallationError(Exception):
    """Raised when a non-recoverable installer error occurs."""


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


class InstallerRollback:
    """Tracks files and directories created during an install attempt.

    On rollback(), removes only tracked paths — never touches pre-existing
    files or any path outside the tracked set.
    """

    def __init__(self) -> None:
        self._files: list[Path] = []
        self._dirs: list[Path] = []

    def track_file(self, path: Path) -> None:
        if path not in self._files:
            self._files.append(path)

    def track_dir(self, path: Path) -> None:
        if path not in self._dirs:
            self._dirs.append(path)

    @property
    def tracked_files(self) -> list[Path]:
        return list(self._files)

    @property
    def tracked_dirs(self) -> list[Path]:
        return list(self._dirs)

    def rollback(self) -> list[str]:
        """Remove all tracked paths. Returns list of successfully removed paths."""
        removed: list[str] = []
        for f in reversed(self._files):
            if f.exists():
                try:
                    f.unlink()
                    removed.append(str(f))
                except OSError:
                    pass
        for d in reversed(self._dirs):
            if d.exists():
                try:
                    shutil.rmtree(d)
                    removed.append(str(d))
                except OSError:
                    pass
        return removed


# ---------------------------------------------------------------------------
# Secret generation
# ---------------------------------------------------------------------------


def generate_secrets() -> InstallerSecrets:
    """Generate all required installation secrets.

    Uses Python's cryptographically secure secrets module.
    The Bash installer uses `openssl rand` for the same purpose.
    Returns an InstallerSecrets — call .masked_summary() for display.
    """
    jwt_secret = secrets.token_urlsafe(_JWT_SECRET_MIN_BYTES)
    rest_api_secret = secrets.token_hex(_REST_SECRET_HEX_BYTES)
    postgres_password = secrets.token_urlsafe(_PG_PASSWORD_BYTES)
    return InstallerSecrets(
        jwt_secret=jwt_secret,
        rest_api_secret=rest_api_secret,
        postgres_password=postgres_password,
    )


def apply_secrets(config: InstallerConfig, sec: InstallerSecrets) -> InstallerConfig:
    """Return a new InstallerConfig with generated secrets applied for any empty fields."""
    from dataclasses import replace

    updates: dict[str, str] = {}
    if not config.jwt_secret:
        updates["jwt_secret"] = sec.jwt_secret
    if not config.rest_api_secret:
        updates["rest_api_secret"] = sec.rest_api_secret
    if not config.postgres_password:
        updates["postgres_password"] = sec.postgres_password
    return replace(config, **updates) if updates else config


# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------


def check_prerequisites(install_dir: Path | None = None) -> list[PrerequisiteResult]:
    """Check all installation prerequisites.

    Checks command *availability* only — does NOT execute Docker, does NOT
    make network connections, does NOT write any files.
    """
    results: list[PrerequisiteResult] = []

    # Python version
    ok = sys.version_info >= (3, 12)
    results.append(PrerequisiteResult(
        name="Python >= 3.12",
        passed=ok,
        message=(
            f"Python {sys.version_info.major}.{sys.version_info.minor}"
            f".{sys.version_info.micro}"
        ),
        fix="Install Python 3.12 or later: https://www.python.org/downloads/",
    ))

    # Docker command availability
    docker_path = shutil.which("docker")
    results.append(PrerequisiteResult(
        name="docker command",
        passed=docker_path is not None,
        message=f"found at {docker_path}" if docker_path else "not found in PATH",
        fix="Install Docker: https://docs.docker.com/get-docker/",
    ))

    # Docker Compose (plugin: `docker compose`; or standalone: `docker-compose`)
    compose_path = shutil.which("docker-compose")
    compose_via_plugin = docker_path is not None
    compose_ok = compose_path is not None or compose_via_plugin
    if compose_path:
        compose_msg = f"docker-compose found at {compose_path}"
    elif compose_via_plugin:
        compose_msg = "docker compose plugin available (via docker command)"
    else:
        compose_msg = "not found"
    results.append(PrerequisiteResult(
        name="docker compose",
        passed=compose_ok,
        message=compose_msg,
        fix="Install Docker Compose: https://docs.docker.com/compose/install/",
    ))

    # openssl (used by Bash installer for secret generation on Linux)
    openssl_path = shutil.which("openssl")
    results.append(PrerequisiteResult(
        name="openssl command",
        passed=openssl_path is not None,
        message=f"found at {openssl_path}" if openssl_path else "not found in PATH",
        fix="Install openssl  (Debian/Ubuntu: apt install openssl)",
    ))

    # Write permission for the install directory
    if install_dir is not None:
        if install_dir.exists():
            writable = os.access(install_dir, os.W_OK)
            msg = "writable" if writable else "not writable"
        else:
            parent = install_dir.parent
            writable = parent.exists() and os.access(parent, os.W_OK)
            msg = "parent writable (dir will be created)" if writable else "parent not writable"
        results.append(PrerequisiteResult(
            name=f"write permission: {install_dir}",
            passed=writable,
            message=msg,
            fix=f"chmod u+w {install_dir.parent}  # or choose a different install directory",
        ))

    return results


def all_prerequisites_passed(results: list[PrerequisiteResult]) -> bool:
    return all(r.passed for r in results)


# ---------------------------------------------------------------------------
# .env file generation
# ---------------------------------------------------------------------------


def generate_env_content(config: InstallerConfig) -> str:
    """Generate .env file content string.

    Does NOT write any file — returns the content as a string.
    BETA_DATABASE_URL is constructed from the individual postgres fields.
    """
    database_url = (
        f"postgresql://{config.postgres_user}:{config.postgres_password}"
        f"@postgres:5432/{config.postgres_db}"
    )
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "# WooPrice Beta — generated environment file",
        f"# Created: {created_at}",
        "# DO NOT COMMIT THIS FILE",
        "",
        f"BETA_ENV={config.env}",
        f"BETA_DOMAIN={config.domain}",
        f"BETA_PORT={config.port}",
        f"BETA_DATABASE_URL={database_url}",
        f"BETA_POSTGRES_DB={config.postgres_db}",
        f"BETA_POSTGRES_USER={config.postgres_user}",
        f"BETA_POSTGRES_PASSWORD={config.postgres_password}",
        f"BETA_JWT_SECRET={config.jwt_secret}",
        f"BETA_REST_API_SECRET={config.rest_api_secret}",
        f"BETA_NEXTCLOUD_URL={config.nextcloud_url}",
        f"BETA_NEXTCLOUD_FILE_PATH={config.nextcloud_file_path}",
        f"BETA_NEXTCLOUD_USERNAME={config.nextcloud_username}",
        f"BETA_NEXTCLOUD_PASSWORD={config.nextcloud_password}",
        f"BETA_WOOCOMMERCE_URL={config.woocommerce_url}",
        f"BETA_WOOCOMMERCE_KEY={config.woocommerce_key}",
        f"BETA_WOOCOMMERCE_SECRET={config.woocommerce_secret}",
        f"BETA_TIMEZONE={config.timezone}",
        f"BETA_CURRENCY={config.currency}",
        f"BETA_ADMIN_EMAIL={config.admin_email}",
        f"BETA_STORAGE_PATH={config.storage_path}",
        f"BETA_BACKUP_PATH={config.backup_path}",
        f"BETA_SSL_MODE={config.ssl_mode}",
    ]
    return "\n".join(lines) + "\n"


def _parse_env_content(content: str) -> dict[str, str]:
    """Parse .env file content into a dict. Ignores comments and blank lines."""
    result: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            result[key] = value.strip()
    return result


def write_env_file(
    content: str,
    path: Path,
    rollback: InstallerRollback | None = None,
) -> None:
    """Write .env content to path with mode 600. Tracks new file in rollback."""
    already_existed = path.exists()
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    if rollback is not None and not already_existed:
        rollback.track_file(path)


# ---------------------------------------------------------------------------
# Managed TOML config generation
# ---------------------------------------------------------------------------


def generate_toml_content(config: InstallerConfig) -> str:
    """Generate managed TOML config content string.

    Secrets are NOT included — they live only in the .env file.
    All values that come from env vars use ${VAR} placeholder syntax
    for B3 placeholder expansion at runtime.
    Does NOT write any file — returns the content as a string.
    """
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "# WooPrice Beta — managed configuration file",
        f"# Generated by installer on {created_at}",
        "# DO NOT EDIT MANUALLY. Use: wooprice configure (B5)",
        "# Secrets are NOT stored here — see .env (mode 600)",
        "",
        "[meta]",
        'version = "beta-1.0.0"',
        f'installed_at = "{created_at}"',
        'installer_version = "1.0.0"',
        "",
        "[app]",
        'env = "${BETA_ENV}"',
        'domain = "${BETA_DOMAIN}"',
        f"port = {config.port}",
        'timezone = "${BETA_TIMEZONE}"',
        'currency = "${BETA_CURRENCY}"',
        'storage_path = "${BETA_STORAGE_PATH}"',
        'backup_path = "${BETA_BACKUP_PATH}"',
        'ssl_mode = "${BETA_SSL_MODE}"',
        f'log_level = "{config.log_level}"',
        "",
        "[database]",
        "# Password: BETA_POSTGRES_PASSWORD env var (never stored here)",
        'postgres_db = "${BETA_POSTGRES_DB}"',
        'postgres_user = "${BETA_POSTGRES_USER}"',
        'postgres_host = "postgres"',
        "postgres_port = 5432",
        "",
        "[source]",
        'type = "nextcloud"',
        'nextcloud_url = "${BETA_NEXTCLOUD_URL}"',
        'nextcloud_file_path = "${BETA_NEXTCLOUD_FILE_PATH}"',
        'nextcloud_username = "${BETA_NEXTCLOUD_USERNAME}"',
        "# Password: BETA_NEXTCLOUD_PASSWORD env var (never stored here)",
        "",
        "[channel]",
        'woocommerce_url = "${BETA_WOOCOMMERCE_URL}"',
        "# Key and secret: BETA_WOOCOMMERCE_KEY, BETA_WOOCOMMERCE_SECRET env vars (never stored here)",
    ]
    return "\n".join(lines) + "\n"


def write_toml_config(
    content: str,
    config_dir: Path,
    rollback: InstallerRollback | None = None,
) -> Path:
    """Write managed TOML config to config_dir/wooprice-beta.toml.

    config_dir must exist (created by setup_storage). Tracks new file in rollback.
    """
    config_path = config_dir / "wooprice-beta.toml"
    already_existed = config_path.exists()
    config_path.write_text(content, encoding="utf-8")
    if rollback is not None and not already_existed:
        rollback.track_file(config_path)
    return config_path


# ---------------------------------------------------------------------------
# Storage setup
# ---------------------------------------------------------------------------


def setup_storage(
    storage_path: Path,
    backup_path: Path,
    rollback: InstallerRollback | None = None,
    dry_run: bool = False,
) -> list[Path]:
    """Create storage directory structure.

    Creates:  storage_path/{logs,config,plugins,uploads,diagnostics}
              backup_path/

    In dry_run mode: returns what would be created without writing anything.
    Tracks newly created directories in rollback.
    """
    dirs_to_create: list[Path] = [
        storage_path / sub for sub in _STORAGE_SUBDIRS
    ] + [backup_path]

    if dry_run:
        return dirs_to_create

    created: list[Path] = []
    for d in dirs_to_create:
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created.append(d)
            if rollback is not None:
                rollback.track_dir(d)
    return created


# ---------------------------------------------------------------------------
# Validation (delegates to B3 Configuration Foundation)
# ---------------------------------------------------------------------------


def validate_generated_config(
    env_dict: dict[str, str] | None = None,
    env_content: str | None = None,
    check_paths: bool = False,
) -> ValidationResult:
    """Validate generated configuration using B3 ConfigValidator.

    Accepts either a pre-parsed env dict or raw .env file content string.
    check_paths=False by default — storage dirs may not exist yet at generation time.
    Never calls sys.exit — returns ValidationResult; caller decides what to do.
    """
    if env_dict is None:
        if env_content is None:
            raise ValueError("Provide env_dict or env_content")
        env_dict = _parse_env_content(env_content)
    validator = ConfigValidator(check_paths=check_paths)
    return validator.validate(env_dict)


# ---------------------------------------------------------------------------
# Dry-run mode
# ---------------------------------------------------------------------------


def dry_run_install(config: InstallerConfig, install_dir: Path) -> DryRunResult:
    """Simulate a full install without writing any files.

    Returns a DryRunResult describing everything that would happen.
    """
    prereqs = check_prerequisites(install_dir=install_dir)
    env_content = generate_env_content(config)
    toml_content = generate_toml_content(config)
    storage_dirs = setup_storage(
        Path(config.storage_path),
        Path(config.backup_path),
        dry_run=True,
    )
    return DryRunResult(
        prerequisites=prereqs,
        env_content=env_content,
        toml_content=toml_content,
        storage_dirs=storage_dirs,
        secrets_would_be_generated=config.needs_secret_generation(),
        files_would_be_written=[
            install_dir / ".env",
            Path(config.storage_path) / "config" / "wooprice-beta.toml",
        ],
    )


# ---------------------------------------------------------------------------
# Confirmation / cancellation
# ---------------------------------------------------------------------------


def confirm_installation(response: str) -> bool:
    """Return True if response is an affirmative confirmation.

    Acceptable: 'y', 'yes', '' (Enter = accept default).
    Everything else cancels.
    """
    return response.strip().lower() in ("y", "yes", "")


def build_confirmation_summary(config: InstallerConfig) -> str:
    """Build a human-readable summary of what will be installed.

    Secrets are masked — never shown in plain text.
    """
    masked_pg = ("*" * 8 + config.postgres_password[-4:]) if config.postgres_password else "[will be generated]"
    masked_jwt = ("*" * 8 + config.jwt_secret[-4:]) if config.jwt_secret else "[will be generated]"
    masked_rest = ("*" * 8 + config.rest_api_secret[-4:]) if config.rest_api_secret else "[will be generated]"

    lines = [
        "━" * 56,
        "  WooPrice Beta — Installation Summary",
        "  [BETA ENVIRONMENT — NOT PRODUCTION]",
        "━" * 56,
        f"  Domain:          {config.domain}:{config.port}",
        f"  SSL mode:        {config.ssl_mode}",
        f"  Postgres DB:     {config.postgres_db}",
        f"  Postgres user:   {config.postgres_user}",
        f"  Postgres pass:   {masked_pg}",
        f"  JWT secret:      {masked_jwt}",
        f"  REST secret:     {masked_rest}",
        f"  Nextcloud URL:   {config.nextcloud_url}",
        f"  WooCommerce URL: {config.woocommerce_url}",
        f"  Timezone:        {config.timezone}",
        f"  Currency:        {config.currency}",
        f"  Admin email:     {config.admin_email}",
        f"  Storage path:    {config.storage_path}",
        f"  Backup path:     {config.backup_path}",
        "━" * 56,
    ]
    return "\n".join(lines)
