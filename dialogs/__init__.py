"""Dialog package re-exporting legacy dialog classes."""

# Re-export all dialog classes and helper functions from the migrated module so
# that ``from dialogs import FooDialog`` continues to work across the project.
from .dialogs import *  # noqa: F401,F403
from .sale_confirmation import SaleConfirmationDialog  # noqa: F401

__all__ = [name for name in globals() if not name.startswith('_')]
