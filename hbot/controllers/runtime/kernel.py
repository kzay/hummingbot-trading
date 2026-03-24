"""Re-export of the shared runtime kernel for clean import paths.

Usage::

    from controllers.runtime.kernel import SharedRuntimeKernel

The kernel lives in ``controllers.shared_mm_v24`` alongside the MM subclass
``EppV24Controller(SharedRuntimeKernel)``.  This module exists so that
directional strategies can import the kernel without referencing the
``shared_mm_v24`` module name.
"""
from controllers.shared_runtime_v24 import SharedRuntimeKernel

__all__ = ["SharedRuntimeKernel"]
