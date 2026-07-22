# ADR 0003: FX conventions

Status: accepted

Original amounts and currencies are immutable. Portfolio valuation uses the official rate for the valuation date: CNB for CZK reporting and ECB as fallback and for EUR crosses.

The broker transaction rate is retained separately and is used to explain actual conversion costs. Weekends and holidays carry the most recent official rate forward with an explicit carried-forward quality flag.

Internal transfers and internal FX conversions are not external cash flows at aggregate portfolio level.
