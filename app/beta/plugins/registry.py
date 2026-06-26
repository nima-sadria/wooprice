"""WooPrice Beta — Plugin Registry.

Maintains the runtime set of active plugins. Provides lookup interface
for all plugin categories. Persists plugin state to beta_plugins table.

Implementation begins in B12.
"""
from typing import Any


class PluginRecord:
    """Runtime record for an installed plugin.

    Implementation begins in B12.
    """
    pass


class PluginRegistry:
    """Maintains the runtime set of active plugins.

    Implementation begins in B12.
    """

    def register(self, plugin_id: str, plugin: Any) -> None:
        """Register a loaded plugin instance.

        Implementation begins in B12.
        """
        raise NotImplementedError("Implementation begins in B12.")

    def get(self, plugin_id: str) -> Any:
        """Return the loaded plugin instance by ID.

        Implementation begins in B12.
        """
        raise NotImplementedError("Implementation begins in B12.")

    def list_all(self) -> list[PluginRecord]:
        """Return all registered plugins.

        Implementation begins in B12.
        """
        raise NotImplementedError("Implementation begins in B12.")

    def list_by_category(self, category: str) -> list[PluginRecord]:
        """Return all registered plugins in the given category.

        Implementation begins in B12.
        """
        raise NotImplementedError("Implementation begins in B12.")

    def is_active(self, plugin_id: str) -> bool:
        """Return True if plugin is active.

        Implementation begins in B12.
        """
        raise NotImplementedError("Implementation begins in B12.")

    def enable(self, plugin_id: str) -> None:
        """Enable an installed plugin.

        Implementation begins in B12.
        """
        raise NotImplementedError("Implementation begins in B12.")

    def disable(self, plugin_id: str) -> None:
        """Disable an active plugin.

        Implementation begins in B12.
        """
        raise NotImplementedError("Implementation begins in B12.")

    def unregister(self, plugin_id: str) -> None:
        """Remove a plugin from the registry.

        Implementation begins in B12.
        """
        raise NotImplementedError("Implementation begins in B12.")
