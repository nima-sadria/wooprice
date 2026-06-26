"""WooPrice Beta — Dummy Channel Adapter (reference plugin implementation).

Logs and acknowledges all change sets without applying them.
Use this as a starting point for custom channel adapter plugins.

Full plugin system implementation begins in B12.
See: docs/beta/PLUGIN_ARCHITECTURE.md
"""


class DummyChannelAdapter:
    """Dummy channel adapter — accepts all change sets without applying them.

    This is the minimal reference implementation of a ChannelAdapterPlugin.
    It demonstrates the required interface without any real I/O.

    Implementation of the base class and real behavior begins in B12.
    """

    def validate_config(self, config: dict) -> None:
        """No configuration required for the dummy adapter."""

    def test_connection(self) -> bool:
        """Dummy adapter is always reachable."""
        return True

    def apply_change_set(self, change_set: object) -> dict:
        """Accept the change set and return a success result without applying it.

        Implementation begins in B12 (real adapters will apply changes here).
        """
        return {
            "applied": 0,
            "failed": 0,
            "dry_run": False,
            "note": "DummyChannelAdapter: no real updates made. Implementation begins in B12.",
        }
