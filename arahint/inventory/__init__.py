"""Core inventory for arahint-erp.

Items carry a base UOM plus optional other UOMs with conversion factors.
Stock entries (receipt, issue, transfer) convert into the base UOM at the
transaction boundary, are valued through one valuation mechanism, and are
recorded in an append-only stock ledger that the reports read back.
"""

from .errors import (
    DuplicateError,
    InventoryError,
    NotFoundError,
    ValidationError,
)
from .service import InventoryService
from .uom import UomConverter, UomConversion
from .valuation import (
    FIFO,
    MOVING_AVERAGE,
    VALUATION_METHODS,
    FifoValuation,
    MovingAverageValuation,
    ValuationRegistry,
    ValuationState,
)

__all__ = [
    "DuplicateError",
    "FIFO",
    "FifoValuation",
    "InventoryError",
    "InventoryService",
    "MOVING_AVERAGE",
    "MovingAverageValuation",
    "NotFoundError",
    "UomConversion",
    "UomConverter",
    "VALUATION_METHODS",
    "ValidationError",
    "ValuationRegistry",
    "ValuationState",
]
