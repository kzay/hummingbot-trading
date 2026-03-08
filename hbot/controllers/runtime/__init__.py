"""Canonical shared runtime namespace for controller families.

Keep this package init lightweight. Import from explicit submodules to avoid
eagerly loading runtime base aliases in stripped test environments.
"""

__all__ = []
