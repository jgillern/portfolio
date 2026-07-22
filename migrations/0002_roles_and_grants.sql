BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'portfolio_app') THEN
    CREATE ROLE portfolio_app NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'portfolio_worker') THEN
    CREATE ROLE portfolio_worker NOLOGIN;
  END IF;
END;
$$;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO portfolio_app, portfolio_worker;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC;

GRANT SELECT ON
  broker,
  instrument,
  listing,
  price,
  fx_rate,
  position_snapshot,
  portfolio_snapshot,
  fund_holding_snapshot,
  exposure_snapshot,
  benchmark,
  benchmark_series,
  app_account,
  app_holding,
  app_transaction,
  app_import_status,
  app_data_quality_issue
TO portfolio_app;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO portfolio_worker;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO portfolio_worker;

REVOKE ALL ON encrypted_secret, secret_access_audit, raw_import FROM portfolio_app;
REVOKE INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public FROM portfolio_app;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO portfolio_worker;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO portfolio_worker;

COMMIT;
