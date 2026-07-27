"""Agentic Fieldbook — repo-root plugin entry point for Hermes Git-install.

Hermes's ``plugins install`` clones this repository into
``~/.hermes/plugins/<name>/`` and expects both ``plugin.yaml`` and a
``register(ctx)`` callable at the *installed* directory root. This module
re-exports the real ``register`` from the importable ``agentic_fieldbook``
package so the repo root satisfies the loader's flat layout while the
package remains importable for tests and pip installs.
"""

from agentic_fieldbook.plugin import register

__version__ = "0.1.0"

__all__ = ["register", "__version__"]
