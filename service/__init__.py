"""Self-hosted service contract for citation badge runtime."""

__version__ = "0.1.0"

from .config import Settings
from .state import empty_status

__all__ = ["Settings", "empty_status", "__version__"]
