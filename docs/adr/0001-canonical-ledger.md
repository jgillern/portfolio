# ADR 0001: Append-only canonical ledger

Status: accepted

The ledger is the only source of truth for economic events. Holdings, performance, income, costs and exposures are derived data.

Posted ledger events, cash legs and execution legs are immutable. Corrections create a reversing event and a replacement event linked to the original. This keeps every reported number explainable and allows parsers to be replayed safely.

Quantities and amounts use PostgreSQL numeric values and decimal strings at API boundaries. Binary floating-point values are not used for financial amounts.
