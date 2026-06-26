"""WooPrice Beta — Placeholder expansion for managed config files.

Resolves ${VAR} placeholders in TOML config text at read time.
Expansion is never written back to disk — config files always retain
the ${VAR} form so they remain environment-portable.
"""

import os
import re

_PLACEHOLDER_RE = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}')


def expand_placeholders(text: str, env: dict[str, str] | None = None) -> str:
    """Replace ${VAR} placeholders in text with values from env.

    Unknown placeholders are left unexpanded (returned as-is).
    If env is None, os.environ is used.
    """
    if env is None:
        env = dict(os.environ)

    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        return env.get(var_name, match.group(0))

    return _PLACEHOLDER_RE.sub(_replace, text)


def find_unexpanded(text: str, env: dict[str, str] | None = None) -> list[str]:
    """Return a list of ${VAR} placeholders that could not be expanded."""
    if env is None:
        env = dict(os.environ)
    return [
        match.group(1)
        for match in _PLACEHOLDER_RE.finditer(text)
        if match.group(1) not in env
    ]
