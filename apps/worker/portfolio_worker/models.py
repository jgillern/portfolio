from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EventType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    DIVIDEND = "DIVIDEND"
    INTEREST = "INTEREST"
    FEE = "FEE"
    TAX = "TAX"
    FX_CONVERSION = "FX_CONVERSION"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    SPLIT = "SPLIT"
    MERGER = "MERGER"
    SPINOFF = "SPINOFF"
    RETURN_OF_CAPITAL = "RETURN_OF_CAPITAL"
    ADJUSTMENT_REVERSAL = "ADJUSTMENT_REVERSAL"


class CashLegType(StrEnum):
    PRINCIPAL = "PRINCIPAL"
    FEE = "FEE"
    TAX = "TAX"
    INCOME_GROSS = "INCOME_GROSS"
    INCOME_NET = "INCOME_NET"
    FX_BUY = "FX_BUY"
    FX_SELL = "FX_SELL"
    OTHER = "OTHER"


class ExecutionLegType(StrEnum):
    WHOLE_SHARE = "WHOLE_SHARE"
    FRACTIONAL_RIGHT = "FRACTIONAL_RIGHT"
    OTHER = "OTHER"


class CashLeg(BaseModel):
    model_config = ConfigDict(frozen=True)

    leg_type: CashLegType
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    amount: Decimal
    broker_fx_rate: Decimal | None = Field(default=None, gt=0)

    @field_validator("amount")
    @classmethod
    def amount_must_not_be_zero(cls, value: Decimal) -> Decimal:
        if value == 0:
            raise ValueError("cash leg amount cannot be zero")
        return value


class NormalizedEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    broker_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    account_ref: str = Field(min_length=1)
    event_type: EventType
    occurred_at: datetime
    trade_date: date | None = None
    settlement_date: date | None = None
    instrument_name: str | None = None
    isin: str | None = Field(default=None, pattern=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
    ticker: str | None = None
    quantity_delta: Decimal | None = None
    unit_price: Decimal | None = Field(default=None, ge=0)
    gross_amount: Decimal | None = None
    gross_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    external_cash_flow: bool = False
    cash_legs: tuple[CashLeg, ...] = ()
    external_order_id: str | None = None
    execution_leg_type: ExecutionLegType | None = None
    metadata: dict[str, Any] = {}

    @field_validator("occurred_at")
    @classmethod
    def occurred_at_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_event_shape(self) -> NormalizedEvent:
        instrument_events = {
            EventType.BUY,
            EventType.SELL,
            EventType.SPLIT,
            EventType.MERGER,
            EventType.SPINOFF,
            EventType.RETURN_OF_CAPITAL,
        }
        if self.event_type in instrument_events and not (self.isin or self.instrument_name):
            raise ValueError("instrument event requires an ISIN or instrument name")
        if (
            self.event_type in {EventType.DEPOSIT, EventType.WITHDRAWAL}
            and not self.external_cash_flow
        ):
            raise ValueError("deposit and withdrawal must be external cash flows")
        if (
            self.trade_date is not None
            and self.settlement_date is not None
            and self.settlement_date < self.trade_date
        ):
            raise ValueError("settlement date cannot precede trade date")
        return self
