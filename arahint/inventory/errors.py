"""Domain errors raised by the inventory package."""

from __future__ import annotations


class InventoryError(Exception):
    """Base class for inventory domain errors."""


class ValidationError(InventoryError):
    """The submitted data violates a domain rule."""


class NotFoundError(InventoryError):
    """A referenced record does not exist."""


class DuplicateError(InventoryError):
    """A record with the same natural key already exists."""
