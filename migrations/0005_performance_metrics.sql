BEGIN;

CREATE OR REPLACE FUNCTION portfolio_fx_factor(
  source_currency text,
  target_currency text,
  as_of_date date
)
RETURNS numeric
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
  SELECT CASE
    WHEN upper(source_currency) = upper(target_currency) THEN 1::numeric
    ELSE (
      SELECT CASE
        WHEN fx.base_currency = upper(source_currency)
          THEN fx.rate
        ELSE 1 / fx.rate
      END
      FROM fx_rate fx
      WHERE fx.rate_date <= as_of_date
        AND (
          (
            fx.base_currency = upper(source_currency)
            AND fx.quote_currency = upper(target_currency)
          )
          OR (
            fx.quote_currency = upper(source_currency)
            AND fx.base_currency = upper(target_currency)
          )
        )
      ORDER BY
        fx.rate_date DESC,
        CASE fx.quality WHEN 'VERIFIED' THEN 0 ELSE 1 END,
        fx.retrieved_at DESC
      LIMIT 1
    )
  END
$$;

ALTER TABLE position_snapshot
  ADD COLUMN cost_basis numeric(38, 18),
  ADD COLUMN unrealized_result numeric(38, 18);

ALTER TABLE portfolio_snapshot
  ADD COLUMN realized_result numeric(38, 18) NOT NULL DEFAULT 0,
  ADD COLUMN unrealized_result numeric(38, 18),
  ADD COLUMN income numeric(38, 18) NOT NULL DEFAULT 0,
  ADD COLUMN fees numeric(38, 18) NOT NULL DEFAULT 0,
  ADD COLUMN taxes numeric(38, 18) NOT NULL DEFAULT 0,
  ADD COLUMN xirr numeric(38, 18);

GRANT EXECUTE ON FUNCTION portfolio_fx_factor(text, text, date)
TO portfolio_app, portfolio_worker;

COMMIT;
