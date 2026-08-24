"""Browser workbench protocol runner."""

__version__ = "0.2.0"

from .errors import WorkbenchError
from .runner import Runner

__all__ = ["Runner", "WorkbenchError", "__version__"]
