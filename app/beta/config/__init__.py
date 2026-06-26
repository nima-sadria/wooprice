"""WooPrice Beta — Configuration Core public API.

All consumers (backend, CLI, installer, tests, worker) import from here.
No web framework, database, or external service dependency anywhere in this package.

Typical usage:

    from app.beta.config import ConfigurationManager

    manager = ConfigurationManager(env_file=Path(".env"))
    manager.load()
    result = manager.validate()
    if not result:
        print(result.format_errors())
        sys.exit(1)
    config = manager.get()
"""

from .expander import expand_placeholders, find_unexpanded
from .loader import ConfigurationError, EnvironmentLoader
from .manager import ConfigurationManager, NotLoadedError, NotValidError
from .migration import ConfigMigration
from .profiles import ConfigProfile
from .schema import BetaConfig
from .secrets import EnvSecretProvider, SecretProvider, SECRET_FIELDS
from .validation import (
    OPTIONAL_FIELDS,
    REQUIRED_FIELDS,
    ConfigValidator,
    FieldError,
    ValidationResult,
)

__all__ = [
    # Manager (primary entry point)
    "ConfigurationManager",
    "NotLoadedError",
    "NotValidError",
    # Schema
    "BetaConfig",
    # Profiles
    "ConfigProfile",
    # Validation
    "ConfigValidator",
    "ValidationResult",
    "FieldError",
    "REQUIRED_FIELDS",
    "OPTIONAL_FIELDS",
    # Secrets
    "SecretProvider",
    "EnvSecretProvider",
    "SECRET_FIELDS",
    # Loading
    "EnvironmentLoader",
    "ConfigurationError",
    # Expansion
    "expand_placeholders",
    "find_unexpanded",
    # Migration
    "ConfigMigration",
]
