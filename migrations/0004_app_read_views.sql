BEGIN;

CREATE OR REPLACE VIEW app_transaction AS
SELECT
  le.id,
  le.occurred_at,
  le.trade_date,
  le.settlement_date,
  le.event_type,
  le.quantity_delta,
  le.unit_price,
  le.gross_amount,
  le.gross_currency,
  le.external_cash_flow,
  le.reverses_event_id,
  aa.broker_code,
  aa.broker_name,
  aa.pseudonym AS account_name,
  aa.tax_wrapper,
  i.name AS instrument_name,
  i.isin,
  coalesce(sum(cl.amount) FILTER (WHERE cl.leg_type = 'FEE'), 0) AS fee_amount,
  coalesce(sum(cl.amount) FILTER (WHERE cl.leg_type = 'TAX'), 0) AS tax_amount,
  ri.status AS source_status,
  le.account_id,
  aa.broker_id
FROM ledger_event le
JOIN app_account aa ON aa.id = le.account_id
LEFT JOIN instrument i ON i.id = le.instrument_id
LEFT JOIN cash_leg cl ON cl.ledger_event_id = le.id
JOIN raw_import ri ON ri.id = le.raw_import_id
GROUP BY
  le.id, aa.broker_code, aa.broker_name, aa.pseudonym, aa.tax_wrapper,
  i.name, i.isin, ri.status, aa.broker_id;

GRANT SELECT ON app_transaction TO portfolio_app;

COMMIT;
