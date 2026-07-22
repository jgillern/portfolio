from decimal import Decimal
from uuid import UUID

import pytest

from portfolio_worker.lots import InsufficientPosition, OpenLot, allocate_fifo


def lot(
    suffix: int,
    *,
    original: str,
    remaining: str,
    cost: str,
) -> OpenLot:
    return OpenLot(
        id=UUID(int=suffix),
        original_quantity=Decimal(original),
        remaining_quantity=Decimal(remaining),
        acquisition_cost=Decimal(cost),
    )


def test_fifo_consumes_oldest_lot_first() -> None:
    allocations = allocate_fifo(
        (
            lot(1, original="10", remaining="10", cost="1000"),
            lot(2, original="10", remaining="10", cost="1200"),
        ),
        Decimal("15"),
    )

    assert [(item.lot_id.int, item.quantity) for item in allocations] == [
        (1, Decimal("10")),
        (2, Decimal("5")),
    ]
    assert [item.allocated_cost for item in allocations] == [
        Decimal("1000"),
        Decimal("600"),
    ]


def test_fifo_uses_proportional_cost_of_partially_open_lot() -> None:
    allocations = allocate_fifo(
        (lot(1, original="8", remaining="3", cost="400"),),
        Decimal("2"),
    )

    assert allocations[0].allocated_cost == Decimal("100")


def test_fifo_rejects_a_sale_larger_than_the_position() -> None:
    with pytest.raises(InsufficientPosition, match="short by 1"):
        allocate_fifo(
            (lot(1, original="2", remaining="2", cost="20"),),
            Decimal("3"),
        )
