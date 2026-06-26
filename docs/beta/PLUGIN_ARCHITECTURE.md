# WooPrice Beta — Plugin Architecture

**Document:** PLUGIN_ARCHITECTURE.md
**Series:** B1 Architecture Blueprint

---

## Overview

The WooPrice Beta plugin system allows operators to extend the platform with custom
source adapters, channel adapters, rule extensions, safety policy extensions, UI
modules, and report modules — without modifying core application code.

All plugins are validated, registered, and managed through the Plugin Registry. Plugins
are enabled by the CLI (`wooprice adapters`) or the Admin UI. No plugin may bypass the
Trusted Execution Path (TEP).

---

## Plugin Categories

| Category | Interface | TEP position | Description |
|---|---|---|---|
| Source Adapter | `SourceAdapterPlugin` | Before TEP (input) | Custom price data sources |
| Channel Adapter | `ChannelAdapterPlugin` | After TEP (output) | Custom sales channel sinks |
| Rule Extension | `RuleExtensionPlugin` | Inside TEP — Rule Engine | Custom transformation rules |
| Safety Policy Extension | `SafetyPolicyPlugin` | Inside TEP — Safety Engine | Custom safety constraints |
| UI Module | `UIModulePlugin` | None | Additional frontend pages/widgets |
| Report Module | `ReportModulePlugin` | None | Custom report generators |

**TEP constraint:** Only Source Adapter, Channel Adapter, Rule Extension, and Safety Policy
plugins interact with the TEP. Rule and Safety plugins may only add to the validation
chain — they may not remove, reorder, or disable existing validations.

---

## Plugin Manifest

Every plugin must contain a `plugin.json` manifest at its root directory. The manifest
is validated against a JSON Schema before installation.

```json
{
  "id": "plugin-id-kebab-case",
  "name": "Human-Readable Plugin Name",
  "version": "1.0.0",
  "category": "source_adapter",
  "author": "Author Name or Org",
  "description": "One-sentence description of what this plugin does",
  "min_wooprice_version": "beta-1.0.0",
  "max_wooprice_version": null,
  "entry_point": "adapter.py",
  "class_name": "MySourceAdapter",
  "permissions": [
    "read:products",
    "write:source_records"
  ],
  "config_schema": {
    "type": "object",
    "properties": {
      "api_url": { "type": "string", "format": "uri" },
      "api_key": { "type": "string", "minLength": 20 }
    },
    "required": ["api_url", "api_key"]
  },
  "tep_position": null,
  "ui_routes": []
}
```

### Manifest fields

| Field | Required | Description |
|---|---|---|
| `id` | Yes | Unique kebab-case identifier; used as primary key |
| `name` | Yes | Display name shown in UI and CLI |
| `version` | Yes | SemVer string |
| `category` | Yes | One of the 6 plugin categories |
| `author` | Yes | Attribution string |
| `description` | Yes | One-line description |
| `min_wooprice_version` | Yes | Minimum platform version required |
| `max_wooprice_version` | No | Maximum platform version compatible with |
| `entry_point` | Yes | Python file relative to plugin root |
| `class_name` | Yes | Class to instantiate from `entry_point` |
| `permissions` | Yes | List of permissions this plugin requires |
| `config_schema` | No | JSON Schema for plugin-specific config values |
| `tep_position` | No | For TEP plugins: `rule_engine` or `safety_engine` |
| `ui_routes` | No | For UI Module plugins: list of route path/component pairs |

---

## Plugin Directory Structure

```
BETA_STORAGE_PATH/plugins/<plugin-id>/
├── plugin.json        # Manifest (required)
├── adapter.py         # Entry point (filename matches manifest entry_point)
├── requirements.txt   # Plugin-specific Python deps (optional)
└── ...                # Additional plugin files
```

Plugins are isolated to their own subdirectory. They may not read from or write to
any other plugin directory. They may not write outside `BETA_STORAGE_PATH/plugins/<plugin-id>/`
except through documented service interfaces.

---

## Plugin Interfaces

### `SourceAdapterPlugin`

```python
from abc import ABC, abstractmethod
from app.a2.sources.base import SourceRecord

class SourceAdapterPlugin(ABC):
    """Base class for custom source adapter plugins."""

    @abstractmethod
    def validate_config(self, config: dict) -> None:
        """Raise ValueError if config is invalid."""

    @abstractmethod
    def test_connection(self) -> bool:
        """Return True if the source is reachable. Raise on connection error."""

    @abstractmethod
    def fetch_records(self) -> list[SourceRecord]:
        """Fetch and return all source records. Must be idempotent."""
```

### `ChannelAdapterPlugin`

```python
from abc import ABC, abstractmethod
from app.a2.models import ChangeSet

class ChannelAdapterPlugin(ABC):
    """Base class for custom channel adapter plugins."""

    @abstractmethod
    def validate_config(self, config: dict) -> None:
        """Raise ValueError if config is invalid."""

    @abstractmethod
    def test_connection(self) -> bool:
        """Return True if the channel is reachable. Raise on connection error."""

    @abstractmethod
    def apply_change_set(self, change_set: ChangeSet) -> dict:
        """Apply a change set to the channel. Return result dict with applied/failed counts."""
```

### `RuleExtensionPlugin`

```python
from abc import ABC, abstractmethod
from app.a2.rules.base import Rule, RuleResult

class RuleExtensionPlugin(ABC):
    """Base class for custom rule extension plugins."""

    @abstractmethod
    def get_rules(self) -> list[Rule]:
        """Return the list of Rule objects this plugin contributes."""
```

### `SafetyPolicyPlugin`

```python
from abc import ABC, abstractmethod
from app.a2.engines.safety.base import SafetyPolicy, SafetyCheckResult

class SafetyPolicyPlugin(ABC):
    """Base class for custom safety policy plugins."""

    @abstractmethod
    def get_policies(self) -> list[SafetyPolicy]:
        """Return the list of SafetyPolicy objects this plugin contributes."""
```

### `UIModulePlugin`

UI Module plugins provide a manifest-declared set of route paths and frontend bundle
entry points. They are served by Nginx from the plugin directory. The host UI loads
them dynamically through `PluginRouteRegistry` at startup.

```json
"ui_routes": [
    {
        "path": "/plugins/my-plugin/overview",
        "component": "ui/index.js",
        "nav_label": "My Plugin",
        "nav_icon": "puzzle"
    }
]
```

### `ReportModulePlugin`

```python
from abc import ABC, abstractmethod

class ReportModulePlugin(ABC):
    """Base class for report module plugins."""

    @abstractmethod
    def generate(self, context: dict) -> bytes:
        """Generate and return the report as bytes (PDF, CSV, or JSON)."""

    @property
    @abstractmethod
    def report_id(self) -> str:
        """Unique report identifier."""

    @property
    @abstractmethod
    def report_name(self) -> str:
        """Human-readable report name."""

    @property
    @abstractmethod
    def output_format(self) -> str:
        """One of: pdf / csv / json"""
```

---

## Plugin Loader (`app/beta/plugins/loader.py`)

The Plugin Loader runs at application startup:

```
Application startup
  ↓
PluginLoader.discover()
  ├── Scan BETA_STORAGE_PATH/plugins/ for subdirectories
  ├── Load and validate plugin.json (JSON Schema)
  └── Compare plugin.json version with min/max_wooprice_version
  ↓
PluginLoader.load(plugin_id)
  ├── Import entry_point Python module
  ├── Instantiate plugin.class_name
  ├── Call plugin.validate_config(stored_config)
  └── Register plugin with appropriate registry
  ↓
PluginRegistry.enable(plugin_id)
  └── Mark plugin as active in database
```

### Load order

1. Source Adapter plugins (registered with the Source Adapter Framework)
2. Safety Policy plugins (appended to Safety Engine policy chain)
3. Rule Extension plugins (appended to Rule Engine rule list)
4. Channel Adapter plugins (registered with the Channel Registry)
5. Report Module plugins (registered with the Report Registry)
6. UI Module plugins (registered with the UI Route Registry)

---

## Plugin Registry (`app/beta/plugins/registry.py`)

The Plugin Registry maintains the runtime set of active plugins and provides the
lookup interface for all plugin categories.

```python
class PluginRegistry:
    def register(self, plugin_id: str, plugin: Any) -> None
    def get(self, plugin_id: str) -> Any
    def list_all(self) -> list[PluginRecord]
    def list_by_category(self, category: str) -> list[PluginRecord]
    def is_active(self, plugin_id: str) -> bool
    def enable(self, plugin_id: str) -> None
    def disable(self, plugin_id: str) -> None
    def unregister(self, plugin_id: str) -> None
```

Plugin state is persisted in the Beta database (`beta_plugins` table):

```
beta_plugins
  id          TEXT PK (plugin-id from manifest)
  name        TEXT
  version     TEXT
  category    TEXT
  is_active   BOOLEAN DEFAULT FALSE
  config_json TEXT  (JSON string of plugin-specific config values)
  installed_at TIMESTAMP
  enabled_at   TIMESTAMP nullable
  disabled_at  TIMESTAMP nullable
```

---

## Plugin Isolation Rules

1. Plugins **may not** import from other plugins.
2. Plugins **may not** import from `app.beta.*` internal modules — only from documented
   public interfaces (`app.a2.*`, `app.beta.plugins.interfaces`).
3. Plugins **may not** access the database directly. Database access is provided only
   through the service interfaces passed to the plugin constructor.
4. Plugins **may not** read or write to `BETA_STORAGE_PATH` outside their own plugin
   directory, except through the file service interface.
5. Plugins **may not** make outbound HTTP calls through anything other than the approved
   HTTP client provided by the plugin host (so that all outbound calls are logged and
   rate-limited).
6. Plugins that violate isolation rules will be quarantined (disabled with a QUARANTINE
   status) on detection.

---

## Permission Model

Each plugin declares the permissions it requires in `plugin.json`. Required permissions
are displayed to the admin at install time and must be explicitly approved. Installing a
plugin implicitly grants those permissions to the plugin within its execution context.

| Permission | Grants |
|---|---|
| `read:products` | Read-only access to product records |
| `write:source_records` | Write to source record staging area |
| `read:change_sets` | Read change set records |
| `write:channel` | Submit updates to channel adapters |
| `read:rules` | Read rule definitions |
| `extend:rules` | Add rules to the Rule Engine (TEP) |
| `extend:safety` | Add policies to the Safety Engine (TEP) |
| `read:ai_insights` | Read advisory insights |
| `read:schedules` | Read schedule records |
| `read:reports` | Access report generation |

A plugin may never grant itself permissions beyond those declared in its manifest.

---

## Plugin Lifecycle

```
install
  ↓ manifest validation
  ↓ version compatibility check
  ↓ permission review and admin approval
  ↓ copy files to BETA_STORAGE_PATH/plugins/<plugin-id>/
  ↓ write beta_plugins record (is_active=false)

enable
  ↓ call PluginLoader.load(plugin_id)
  ↓ call plugin.validate_config()
  ↓ register with appropriate registry
  ↓ set is_active=true in database

disable
  ↓ unregister from all registries
  ↓ set is_active=false in database
  ↓ services that depend on this plugin degrade gracefully

remove
  ↓ must be disabled first
  ↓ delete files from BETA_STORAGE_PATH/plugins/<plugin-id>/
  ↓ delete beta_plugins record

update
  ↓ disable existing version
  ↓ install new version (validates new manifest)
  ↓ enable new version
  ↓ old version files deleted on success
```

---

## Example Plugin: Dummy Channel Adapter

```python
# plugins/examples/dummy_channel/adapter.py
from app.beta.plugins.interfaces import ChannelAdapterPlugin
from app.a2.models import ChangeSet

class DummyChannelAdapter(ChannelAdapterPlugin):
    """Dummy channel adapter — logs and acknowledges all change sets without applying them."""

    def validate_config(self, config: dict) -> None:
        pass  # No config required

    def test_connection(self) -> bool:
        return True

    def apply_change_set(self, change_set: ChangeSet) -> dict:
        return {
            "applied": len(change_set.changes),
            "failed": 0,
            "dry_run": False,
            "note": "DummyChannelAdapter: no real updates made"
        }
```

---

## Plugin Development Guide Reference

Full plugin development guide is in [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md).
Plugin testing approach is covered in the Testing section of that document.
