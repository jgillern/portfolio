BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE tax_wrapper AS ENUM ('DIP', 'STANDARD');
CREATE TYPE instrument_legal_type AS ENUM (
  'ETF', 'STOCK', 'MUTUAL_FUND', 'BOND', 'CROWDFUNDING',
  'PENSION_PRODUCT', 'CASH', 'FRACTIONAL_RIGHT', 'OTHER'
);
CREATE TYPE economic_asset_class AS ENUM (
  'EQUITY', 'FIXED_INCOME', 'REAL_ESTATE', 'PRIVATE_EQUITY',
  'CASH', 'COMMODITY', 'OTHER'
);
CREATE TYPE ledger_event_type AS ENUM (
  'BUY', 'SELL', 'DEPOSIT', 'WITHDRAWAL', 'DIVIDEND', 'INTEREST',
  'FEE', 'TAX', 'FX_CONVERSION', 'TRANSFER_IN', 'TRANSFER_OUT',
  'SPLIT', 'MERGER', 'SPINOFF', 'RETURN_OF_CAPITAL',
  'ADJUSTMENT_REVERSAL'
);
CREATE TYPE import_status AS ENUM (
  'RECEIVED', 'VALIDATED', 'PARSED', 'MATCHED', 'POSTED',
  'RECONCILED', 'DUPLICATE', 'REVIEW', 'ERROR'
);
CREATE TYPE data_quality AS ENUM (
  'VERIFIED', 'ESTIMATED', 'PARTIAL', 'STALE', 'MISSING', 'CARRIED_FORWARD'
);
CREATE TYPE issue_severity AS ENUM ('INFO', 'WARNING', 'ERROR', 'CRITICAL');
CREATE TYPE issue_status AS ENUM ('OPEN', 'ACKNOWLEDGED', 'RESOLVED');
CREATE TYPE job_status AS ENUM ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'PARTIAL');
CREATE TYPE exposure_dimension AS ENUM (
  'ASSET_CLASS', 'SECTOR', 'GEOGRAPHY', 'CURRENCY', 'UNDERLYING'
);
CREATE TYPE exposure_source AS ENUM ('DIRECT', 'LOOK_THROUGH', 'UNKNOWN');

CREATE TABLE broker (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code text NOT NULL UNIQUE CHECK (code = upper(code)),
  display_name text NOT NULL,
  adapter_version text NOT NULL DEFAULT '1',
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE account (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  broker_id uuid NOT NULL REFERENCES broker(id),
  pseudonym text NOT NULL,
  external_ref_hash bytea,
  tax_wrapper tax_wrapper NOT NULL,
  base_currency char(3) NOT NULL CHECK (base_currency = upper(base_currency)),
  active_from date,
  active_to date,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (broker_id, pseudonym),
  CHECK (active_to IS NULL OR active_from IS NULL OR active_to >= active_from)
);

CREATE TABLE instrument (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  isin char(12) UNIQUE,
  name text NOT NULL,
  legal_type instrument_legal_type NOT NULL,
  asset_class economic_asset_class NOT NULL,
  domicile_country char(2),
  issuer text,
  short_allowed boolean NOT NULL DEFAULT false,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (isin IS NULL OR isin ~ '^[A-Z]{2}[A-Z0-9]{9}[0-9]$')
);

CREATE TABLE listing (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  instrument_id uuid NOT NULL REFERENCES instrument(id),
  mic char(4) NOT NULL,
  ticker text NOT NULL,
  trading_currency char(3) NOT NULL,
  provider_symbols jsonb NOT NULL DEFAULT '{}'::jsonb,
  is_primary boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (instrument_id, mic, ticker, trading_currency)
);

CREATE UNIQUE INDEX listing_one_primary_per_instrument
  ON listing (instrument_id) WHERE is_primary;

CREATE TABLE raw_import (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  broker_id uuid NOT NULL REFERENCES broker(id),
  account_id uuid REFERENCES account(id),
  source_channel text NOT NULL CHECK (source_channel IN ('GMAIL', 'UPLOAD', 'BACKFILL', 'SYNTHETIC')),
  document_type text NOT NULL,
  gmail_message_id text,
  mime_part_id text,
  source_fingerprint char(64) NOT NULL UNIQUE,
  encrypted_blob_key text,
  parser_version text NOT NULL,
  status import_status NOT NULL DEFAULT 'RECEIVED',
  received_at timestamptz NOT NULL,
  period_from date,
  period_to date,
  found_count integer NOT NULL DEFAULT 0 CHECK (found_count >= 0),
  accepted_count integer NOT NULL DEFAULT 0 CHECK (accepted_count >= 0),
  rejected_count integer NOT NULL DEFAULT 0 CHECK (rejected_count >= 0),
  error_code text,
  redacted_error jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (source_fingerprint ~ '^[0-9a-f]{64}$')
);

CREATE INDEX raw_import_status_created_idx ON raw_import (status, created_at DESC);
CREATE INDEX raw_import_account_received_idx ON raw_import (account_id, received_at DESC);

CREATE TABLE broker_order (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id uuid NOT NULL REFERENCES account(id),
  raw_import_id uuid NOT NULL REFERENCES raw_import(id),
  external_order_id text,
  ordered_at timestamptz,
  executed_at timestamptz,
  side text CHECK (side IN ('BUY', 'SELL')),
  summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE execution_leg (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  broker_order_id uuid NOT NULL REFERENCES broker_order(id),
  instrument_id uuid NOT NULL REFERENCES instrument(id),
  listing_id uuid REFERENCES listing(id),
  leg_type text NOT NULL CHECK (leg_type IN ('WHOLE_SHARE', 'FRACTIONAL_RIGHT', 'OTHER')),
  quantity numeric(38, 18) NOT NULL CHECK (quantity > 0),
  price numeric(38, 18) NOT NULL CHECK (price >= 0),
  price_currency char(3) NOT NULL,
  executed_at timestamptz NOT NULL,
  venue text,
  fee_amount numeric(38, 18) NOT NULL DEFAULT 0 CHECK (fee_amount >= 0),
  source_fingerprint char(64) NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (source_fingerprint ~ '^[0-9a-f]{64}$')
);

CREATE TABLE ledger_event (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id uuid NOT NULL REFERENCES account(id),
  instrument_id uuid REFERENCES instrument(id),
  raw_import_id uuid NOT NULL REFERENCES raw_import(id),
  execution_leg_id uuid REFERENCES execution_leg(id),
  event_type ledger_event_type NOT NULL,
  occurred_at timestamptz NOT NULL,
  trade_date date,
  settlement_date date,
  quantity_delta numeric(38, 18),
  unit_price numeric(38, 18),
  gross_amount numeric(38, 18),
  gross_currency char(3),
  external_cash_flow boolean NOT NULL DEFAULT false,
  source_fingerprint char(64) NOT NULL UNIQUE,
  reverses_event_id uuid UNIQUE REFERENCES ledger_event(id),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  posted_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (source_fingerprint ~ '^[0-9a-f]{64}$'),
  CHECK (settlement_date IS NULL OR trade_date IS NULL OR settlement_date >= trade_date),
  CHECK (
    (event_type IN ('BUY', 'SELL', 'SPLIT', 'MERGER', 'SPINOFF', 'RETURN_OF_CAPITAL')
      AND instrument_id IS NOT NULL)
    OR event_type NOT IN ('BUY', 'SELL', 'SPLIT', 'MERGER', 'SPINOFF', 'RETURN_OF_CAPITAL')
  ),
  CHECK (
    event_type NOT IN ('DEPOSIT', 'WITHDRAWAL')
    OR external_cash_flow
  ),
  CHECK (
    event_type <> 'ADJUSTMENT_REVERSAL'
    OR reverses_event_id IS NOT NULL
  )
);

CREATE INDEX ledger_event_account_time_idx ON ledger_event (account_id, occurred_at DESC);
CREATE INDEX ledger_event_instrument_time_idx ON ledger_event (instrument_id, occurred_at DESC);
CREATE INDEX ledger_event_type_time_idx ON ledger_event (event_type, occurred_at DESC);

CREATE TABLE cash_leg (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ledger_event_id uuid NOT NULL REFERENCES ledger_event(id),
  leg_type text NOT NULL CHECK (
    leg_type IN ('PRINCIPAL', 'FEE', 'TAX', 'INCOME_GROSS', 'INCOME_NET', 'FX_BUY', 'FX_SELL', 'OTHER')
  ),
  currency char(3) NOT NULL,
  amount numeric(38, 18) NOT NULL,
  broker_fx_rate numeric(38, 18),
  source_fingerprint char(64) NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (amount <> 0),
  CHECK (broker_fx_rate IS NULL OR broker_fx_rate > 0),
  CHECK (source_fingerprint ~ '^[0-9a-f]{64}$')
);

CREATE INDEX cash_leg_event_idx ON cash_leg (ledger_event_id);

CREATE TABLE lot (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id uuid NOT NULL REFERENCES account(id),
  instrument_id uuid NOT NULL REFERENCES instrument(id),
  opening_event_id uuid NOT NULL UNIQUE REFERENCES ledger_event(id),
  opened_at timestamptz NOT NULL,
  original_quantity numeric(38, 18) NOT NULL CHECK (original_quantity > 0),
  remaining_quantity numeric(38, 18) NOT NULL CHECK (remaining_quantity >= 0),
  acquisition_cost numeric(38, 18) NOT NULL,
  cost_currency char(3) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (remaining_quantity <= original_quantity)
);

CREATE TABLE lot_allocation (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lot_id uuid NOT NULL REFERENCES lot(id),
  closing_event_id uuid NOT NULL REFERENCES ledger_event(id),
  quantity numeric(38, 18) NOT NULL CHECK (quantity > 0),
  allocated_cost numeric(38, 18) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (lot_id, closing_event_id)
);

CREATE TABLE encrypted_secret (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id uuid REFERENCES account(id),
  secret_type text NOT NULL CHECK (secret_type IN ('GMAIL_REFRESH_TOKEN', 'XTB_PDF_PASSWORD')),
  ciphertext bytea NOT NULL,
  nonce bytea NOT NULL CHECK (octet_length(nonce) = 12),
  auth_tag bytea NOT NULL CHECK (octet_length(auth_tag) = 16),
  aad_hash bytea NOT NULL CHECK (octet_length(aad_hash) = 32),
  key_version integer NOT NULL CHECK (key_version > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  superseded_at timestamptz,
  CHECK (
    (secret_type = 'XTB_PDF_PASSWORD' AND account_id IS NOT NULL)
    OR secret_type <> 'XTB_PDF_PASSWORD'
  )
);

CREATE UNIQUE INDEX encrypted_secret_active_unique
  ON encrypted_secret (coalesce(account_id, '00000000-0000-0000-0000-000000000000'::uuid), secret_type)
  WHERE superseded_at IS NULL;

CREATE TABLE secret_access_audit (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  encrypted_secret_id uuid NOT NULL REFERENCES encrypted_secret(id),
  action text NOT NULL CHECK (action IN ('CREATE', 'DECRYPT', 'ROTATE', 'SUPERSEDE')),
  job_run_id uuid,
  outcome text NOT NULL CHECK (outcome IN ('SUCCESS', 'DENIED', 'FAILED')),
  occurred_at timestamptz NOT NULL DEFAULT now(),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE price (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  listing_id uuid REFERENCES listing(id),
  instrument_id uuid NOT NULL REFERENCES instrument(id),
  price_date date NOT NULL,
  close numeric(38, 18) NOT NULL CHECK (close >= 0),
  currency char(3) NOT NULL,
  provider text NOT NULL,
  quality data_quality NOT NULL,
  retrieved_at timestamptz NOT NULL,
  license_note text,
  UNIQUE (instrument_id, listing_id, price_date, provider)
);

CREATE INDEX price_lookup_idx ON price (instrument_id, price_date DESC, quality);

CREATE TABLE fx_rate (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  rate_date date NOT NULL,
  base_currency char(3) NOT NULL,
  quote_currency char(3) NOT NULL,
  rate numeric(38, 18) NOT NULL CHECK (rate > 0),
  provider text NOT NULL,
  quality data_quality NOT NULL,
  retrieved_at timestamptz NOT NULL,
  convention text NOT NULL,
  UNIQUE (rate_date, base_currency, quote_currency, provider),
  CHECK (base_currency <> quote_currency)
);

CREATE INDEX fx_rate_lookup_idx
  ON fx_rate (base_currency, quote_currency, rate_date DESC, quality);

CREATE TABLE position_snapshot (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  snapshot_date date NOT NULL,
  account_id uuid NOT NULL REFERENCES account(id),
  instrument_id uuid NOT NULL REFERENCES instrument(id),
  quantity numeric(38, 18) NOT NULL,
  price_id uuid REFERENCES price(id),
  fx_rate_id uuid REFERENCES fx_rate(id),
  market_value numeric(38, 18),
  reporting_currency char(3) NOT NULL,
  quality data_quality NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (snapshot_date, account_id, instrument_id, reporting_currency)
);

CREATE TABLE portfolio_snapshot (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  snapshot_date date NOT NULL,
  reporting_currency char(3) NOT NULL,
  account_id uuid REFERENCES account(id),
  tax_wrapper tax_wrapper,
  market_value numeric(38, 18) NOT NULL,
  net_external_flow numeric(38, 18) NOT NULL DEFAULT 0,
  daily_twr numeric(38, 18),
  cumulative_twr numeric(38, 18),
  price_set_as_of timestamptz NOT NULL,
  fx_set_as_of timestamptz NOT NULL,
  quality data_quality NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE NULLS NOT DISTINCT (snapshot_date, reporting_currency, account_id, tax_wrapper)
);

CREATE TABLE fund_holding_snapshot (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  fund_instrument_id uuid NOT NULL REFERENCES instrument(id),
  holding_date date NOT NULL,
  underlying_instrument_id uuid REFERENCES instrument(id),
  underlying_name text NOT NULL,
  underlying_isin char(12),
  country_code char(2),
  sector text,
  economic_currency char(3),
  weight numeric(20, 16) NOT NULL CHECK (weight >= 0 AND weight <= 1),
  provider text NOT NULL,
  retrieved_at timestamptz NOT NULL,
  UNIQUE (
    fund_instrument_id, holding_date, underlying_name,
    country_code, sector, economic_currency
  )
);

CREATE TABLE exposure_snapshot (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  snapshot_date date NOT NULL,
  reporting_currency char(3) NOT NULL,
  account_id uuid REFERENCES account(id),
  tax_wrapper tax_wrapper,
  dimension exposure_dimension NOT NULL,
  exposure_key text NOT NULL,
  label text NOT NULL,
  source exposure_source NOT NULL,
  value numeric(38, 18) NOT NULL,
  weight numeric(20, 16) NOT NULL CHECK (weight >= 0 AND weight <= 1),
  coverage numeric(20, 16) NOT NULL CHECK (coverage >= 0 AND coverage <= 1),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE NULLS NOT DISTINCT (
    snapshot_date, reporting_currency, account_id, tax_wrapper,
    dimension, exposure_key, source
  )
);

CREATE TABLE benchmark (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code text NOT NULL UNIQUE CHECK (code IN ('SP500', 'MSCI_WORLD', 'MSCI_ACWI')),
  display_name text NOT NULL,
  proxy_instrument_id uuid NOT NULL REFERENCES instrument(id),
  proxy_listing_id uuid REFERENCES listing(id),
  methodology_version text NOT NULL,
  valid_from date NOT NULL,
  valid_to date
);

CREATE TABLE benchmark_series (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  benchmark_id uuid NOT NULL REFERENCES benchmark(id),
  series_date date NOT NULL,
  reporting_currency char(3) NOT NULL,
  normalized_value numeric(38, 18) NOT NULL CHECK (normalized_value >= 0),
  price_id uuid REFERENCES price(id),
  fx_rate_id uuid REFERENCES fx_rate(id),
  quality data_quality NOT NULL,
  UNIQUE (benchmark_id, series_date, reporting_currency)
);

CREATE TABLE job_run (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_type text NOT NULL,
  idempotency_key text NOT NULL UNIQUE,
  status job_status NOT NULL DEFAULT 'QUEUED',
  checkpoint jsonb NOT NULL DEFAULT '{}'::jsonb,
  attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
  scheduled_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  finished_at timestamptz,
  last_error_code text,
  redacted_error jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE secret_access_audit
  ADD CONSTRAINT secret_access_audit_job_run_fk
  FOREIGN KEY (job_run_id) REFERENCES job_run(id);

CREATE TABLE connector_state (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  connector text NOT NULL UNIQUE CHECK (connector IN ('GMAIL_GEORGE', 'GMAIL_XTB', 'GMAIL_PATRIA', 'CNB_FX', 'ECB_FX', 'MARKET_DATA', 'FUND_HOLDINGS', 'BACKUP')),
  checkpoint jsonb NOT NULL DEFAULT '{}'::jsonb,
  last_checked_at timestamptz,
  last_received_at timestamptz,
  last_success_at timestamptz,
  imported_count bigint NOT NULL DEFAULT 0 CHECK (imported_count >= 0),
  duplicate_count bigint NOT NULL DEFAULT 0 CHECK (duplicate_count >= 0),
  error_count bigint NOT NULL DEFAULT 0 CHECK (error_count >= 0),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE reconciliation_run (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id uuid NOT NULL REFERENCES account(id),
  raw_import_id uuid REFERENCES raw_import(id),
  period_end date NOT NULL,
  status text NOT NULL CHECK (status IN ('MATCHED', 'DIFFERENCE', 'ERROR')),
  position_tolerance numeric(38, 18) NOT NULL,
  cash_tolerance numeric(38, 18) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE reconciliation_item (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  reconciliation_run_id uuid NOT NULL REFERENCES reconciliation_run(id),
  item_type text NOT NULL CHECK (item_type IN ('POSITION', 'CASH')),
  instrument_id uuid REFERENCES instrument(id),
  currency char(3),
  expected numeric(38, 18) NOT NULL,
  actual numeric(38, 18) NOT NULL,
  difference numeric(38, 18) GENERATED ALWAYS AS (actual - expected) STORED,
  within_tolerance boolean NOT NULL,
  UNIQUE NULLS NOT DISTINCT (reconciliation_run_id, item_type, instrument_id, currency)
);

CREATE TABLE data_quality_issue (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code text NOT NULL,
  severity issue_severity NOT NULL,
  status issue_status NOT NULL DEFAULT 'OPEN',
  account_id uuid REFERENCES account(id),
  instrument_id uuid REFERENCES instrument(id),
  raw_import_id uuid REFERENCES raw_import(id),
  reconciliation_item_id uuid REFERENCES reconciliation_item(id),
  summary text NOT NULL,
  details jsonb NOT NULL DEFAULT '{}'::jsonb,
  detected_at timestamptz NOT NULL DEFAULT now(),
  acknowledged_at timestamptz,
  resolved_at timestamptz,
  resolution_note text
);

CREATE INDEX data_quality_open_idx
  ON data_quality_issue (severity, detected_at DESC) WHERE status <> 'RESOLVED';

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

CREATE TRIGGER broker_set_updated_at
BEFORE UPDATE ON broker FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER account_set_updated_at
BEFORE UPDATE ON account FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER instrument_set_updated_at
BEFORE UPDATE ON instrument FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER raw_import_set_updated_at
BEFORE UPDATE ON raw_import FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER connector_state_set_updated_at
BEFORE UPDATE ON connector_state FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE FUNCTION reject_immutable_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'append-only relation % cannot be updated or deleted', TG_TABLE_NAME
    USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER ledger_event_immutable
BEFORE UPDATE OR DELETE ON ledger_event
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

CREATE TRIGGER cash_leg_immutable
BEFORE UPDATE OR DELETE ON cash_leg
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

CREATE TRIGGER execution_leg_immutable
BEFORE UPDATE OR DELETE ON execution_leg
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

CREATE VIEW app_account AS
SELECT
  a.id,
  a.broker_id,
  b.code AS broker_code,
  b.display_name AS broker_name,
  a.pseudonym,
  a.tax_wrapper,
  a.base_currency,
  a.active_from,
  a.active_to
FROM account a
JOIN broker b ON b.id = a.broker_id;

CREATE VIEW app_holding AS
WITH positions AS (
  SELECT
    le.account_id,
    le.instrument_id,
    sum(coalesce(le.quantity_delta, 0)) AS quantity
  FROM ledger_event le
  WHERE le.instrument_id IS NOT NULL
  GROUP BY le.account_id, le.instrument_id
)
SELECT
  p.account_id,
  p.instrument_id,
  i.isin,
  i.name,
  i.legal_type,
  i.asset_class,
  p.quantity,
  aa.broker_code,
  aa.broker_name,
  aa.pseudonym AS account_name,
  aa.tax_wrapper
FROM positions p
JOIN instrument i ON i.id = p.instrument_id
JOIN app_account aa ON aa.id = p.account_id
WHERE p.quantity <> 0;

CREATE VIEW app_transaction AS
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
  ri.status AS source_status
FROM ledger_event le
JOIN app_account aa ON aa.id = le.account_id
LEFT JOIN instrument i ON i.id = le.instrument_id
LEFT JOIN cash_leg cl ON cl.ledger_event_id = le.id
JOIN raw_import ri ON ri.id = le.raw_import_id
GROUP BY
  le.id, aa.broker_code, aa.broker_name, aa.pseudonym, aa.tax_wrapper,
  i.name, i.isin, ri.status;

CREATE VIEW app_import_status AS
SELECT
  cs.connector,
  cs.last_checked_at,
  cs.last_received_at,
  cs.last_success_at,
  cs.imported_count,
  cs.duplicate_count,
  cs.error_count,
  CASE
    WHEN cs.last_success_at IS NULL THEN 'not_configured'
    WHEN cs.error_count > 0 AND cs.last_success_at < now() - interval '1 day' THEN 'error'
    WHEN cs.last_success_at < now() - interval '3 days' THEN 'stale'
    ELSE 'healthy'
  END AS status
FROM connector_state cs;

CREATE VIEW app_data_quality_issue AS
SELECT
  dqi.id,
  dqi.code,
  lower(dqi.severity::text) AS severity,
  lower(dqi.status::text) AS status,
  dqi.summary,
  dqi.detected_at,
  dqi.acknowledged_at,
  dqi.resolved_at,
  dqi.account_id,
  dqi.instrument_id
FROM data_quality_issue dqi;

INSERT INTO broker (code, display_name) VALUES
  ('GEORGE', 'Česká spořitelna / George'),
  ('XTB', 'XTB'),
  ('PATRIA', 'Patria Finance');

INSERT INTO connector_state (connector) VALUES
  ('GMAIL_GEORGE'),
  ('GMAIL_XTB'),
  ('GMAIL_PATRIA'),
  ('CNB_FX'),
  ('ECB_FX'),
  ('MARKET_DATA'),
  ('FUND_HOLDINGS'),
  ('BACKUP');

COMMIT;
