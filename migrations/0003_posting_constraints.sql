BEGIN;

CREATE UNIQUE INDEX broker_order_source_unique
  ON broker_order (account_id, raw_import_id, external_order_id)
  WHERE external_order_id IS NOT NULL;

COMMIT;
