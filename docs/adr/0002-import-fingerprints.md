# ADR 0002: Layered import fingerprints

Status: accepted

Idempotence is enforced at two levels.

A raw source fingerprint identifies a Gmail message, attachment, canonical HTML body or uploaded document. An economic fingerprint identifies a normalized broker event. Both are scoped by broker and account where appropriate.

External order identifiers are evidence, not universal unique keys. XTB whole-share and fractional-right legs can share an order number, so an execution fingerprint also includes leg type, instrument, quantity, price and execution time.

Duplicate inputs are recorded as duplicate attempts but never post another ledger event.
