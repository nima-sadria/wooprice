"""WooPrice Beta — Plugin Manifest validator.

Validates plugin.json manifests against the JSON Schema before installation.
Checks version compatibility with the running platform version.

Implementation begins in B12.
"""


class ManifestValidationError(Exception):
    """Raised when a plugin manifest fails validation."""
    pass


class PluginManifest:
    """Validated plugin manifest parsed from plugin.json.

    Implementation begins in B12.
    """
    pass


def validate_manifest(manifest_path: str) -> PluginManifest:
    """Validate a plugin.json file against the manifest schema.

    Raises ManifestValidationError if invalid.

    Implementation begins in B12.
    """
    raise NotImplementedError("Implementation begins in B12.")
