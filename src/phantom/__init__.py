"""Phantom — Automated documentation asset generation."""

from phantom.contract import CONTRACT_VERSION

__version__ = "0.4.0"

# The consumer-facing contract version (see CONTRACT.md). Versioned
# independently of ``__version__`` — consumers pin the package but assert
# against ``CONTRACT_VERSION``.
__contract_version__ = CONTRACT_VERSION

__all__ = ["CONTRACT_VERSION", "__contract_version__", "__version__"]
