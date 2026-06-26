"""WooPrice Beta — Direct managed config file reader.

Used by pre-server CLI commands (install, configure) that run before
the application server is started. Reads the managed TOML config file directly.

Implementation begins in B3.
"""


class ConfigReader:
    """Reads the managed TOML config file directly (no running server required).

    Implementation begins in B3.
    """

    def read(self) -> dict:
        """Read and return the managed config file as a dict.

        Implementation begins in B3.
        """
        raise NotImplementedError("Implementation begins in B3.")

    def write(self, config: dict) -> None:
        """Write an updated config dict to the managed config file.

        Implementation begins in B3.
        """
        raise NotImplementedError("Implementation begins in B3.")
