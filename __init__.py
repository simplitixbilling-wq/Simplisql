"""
SimplSQL Modules Package
------------------------
Modular components for the SimplSQL application.

Modules:
- ai: AI assistant and provider integrations
- ui: User interface components and dialogs
- core: Database operations and data loading
- utils: Utility functions and helpers
"""

__version__ = "1.0.0"
__author__ = "SimplSQL Team"

# Keep package initialization lightweight to avoid circular imports during test discovery.
# Subpackages can be imported explicitly where needed (e.g., from SimpliSql import core).
__all__ = ['ai', 'ui', 'core', 'utils']
