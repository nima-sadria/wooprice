from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import SourceAdapter


class DuplicateSourceTypeError(Exception):
    pass


class UnknownSourceTypeError(KeyError):
    pass


class SourceRegistry:
    """
    Central registry mapping source type identifiers to adapter classes.

    Future adapters are registered here without modifying core logic.
    """

    def __init__(self) -> None:
        self._registry: dict[str, type[SourceAdapter]] = {}

    def register(self, source_type: str, adapter_class: type[SourceAdapter]) -> None:
        if source_type in self._registry:
            raise DuplicateSourceTypeError(
                f"Source type '{source_type}' is already registered."
            )
        self._registry[source_type] = adapter_class

    def resolve(self, source_type: str) -> type[SourceAdapter]:
        if source_type not in self._registry:
            raise UnknownSourceTypeError(
                f"Unknown source type: '{source_type}'. "
                f"Registered types: {sorted(self._registry)}"
            )
        return self._registry[source_type]

    def registered_types(self) -> list[str]:
        return sorted(self._registry)


# Module-level singleton registry
_default_registry = SourceRegistry()


def get_registry() -> SourceRegistry:
    return _default_registry
