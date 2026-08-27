"""AI Interviewer service package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ai-interviewer-platform")
except PackageNotFoundError:  # pragma: no cover - supports direct source inspection
    __version__ = "0.1.0"

__all__ = ["__version__"]
