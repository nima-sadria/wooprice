"""WooPrice Beta — Plugin Loader.

Discovers, validates, and loads plugin packages from the plugin directory.
Registers loaded plugins with the Plugin Registry.

Implementation begins in B12.
"""


class PluginLoader:
    """Discovers and loads plugins from the plugin directory.

    Implementation begins in B12.
    """

    def discover(self) -> list[str]:
        """Scan BETA_STORAGE_PATH/plugins/ and return plugin IDs found.

        Implementation begins in B12.
        """
        raise NotImplementedError("Implementation begins in B12.")

    def load(self, plugin_id: str) -> None:
        """Load and register a single plugin by ID.

        Implementation begins in B12.
        """
        raise NotImplementedError("Implementation begins in B12.")

    def load_all(self) -> None:
        """Discover and load all enabled plugins at startup.

        Implementation begins in B12.
        """
        raise NotImplementedError("Implementation begins in B12.")
