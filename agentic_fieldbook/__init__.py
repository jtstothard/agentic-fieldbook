"""Agentic Fieldbook — an operating methodology for autonomous agents."""

__version__ = "0.1.0"

# Hermes loads directory plugins through this package's register(ctx) hook.
from .plugin import register

__all__ = ["register", "__version__"]
