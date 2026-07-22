from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID


class InsufficientPosition(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class OpenLot:
    id: UUID
    original_quantity: Decimal
    remaining_quantity: Decimal
    acquisition_cost: Decimal


@dataclass(frozen=True, slots=True)
class LotAllocation:
    lot_id: UUID
    quantity: Decimal
    allocated_cost: Decimal


def allocate_fifo(
    lots: tuple[OpenLot, ...],
    closing_quantity: Decimal,
) -> tuple[LotAllocation, ...]:
    if closing_quantity <= 0:
        raise ValueError("closing quantity must be positive")

    remaining = closing_quantity
    allocations: list[LotAllocation] = []
    for lot in lots:
        if remaining == 0:
            break
        if lot.original_quantity <= 0 or lot.remaining_quantity < 0:
            raise ValueError("lot quantities must be valid")
        quantity = min(remaining, lot.remaining_quantity)
        if quantity == 0:
            continue
        allocations.append(
            LotAllocation(
                lot_id=lot.id,
                quantity=quantity,
                allocated_cost=lot.acquisition_cost
                * quantity
                / lot.original_quantity,
            )
        )
        remaining -= quantity

    if remaining > 0:
        raise InsufficientPosition(
            f"position is short by {remaining} units"
        )
    return tuple(allocations)
