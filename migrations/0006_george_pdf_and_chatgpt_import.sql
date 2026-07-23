BEGIN;

ALTER TABLE encrypted_secret
  DROP CONSTRAINT IF EXISTS encrypted_secret_secret_type_check;

ALTER TABLE encrypted_secret
  ADD CONSTRAINT encrypted_secret_secret_type_check
  CHECK (
    secret_type IN (
      'GMAIL_REFRESH_TOKEN',
      'XTB_PDF_PASSWORD',
      'GEORGE_PDF_PASSWORD'
    )
  );

ALTER TABLE encrypted_secret
  DROP CONSTRAINT IF EXISTS encrypted_secret_check;

ALTER TABLE encrypted_secret
  ADD CONSTRAINT encrypted_secret_account_scope_check
  CHECK (
    (
      secret_type IN ('XTB_PDF_PASSWORD', 'GEORGE_PDF_PASSWORD')
      AND account_id IS NOT NULL
    )
    OR (
      secret_type = 'GMAIL_REFRESH_TOKEN'
      AND account_id IS NULL
    )
  );

ALTER TABLE raw_import
  DROP CONSTRAINT IF EXISTS raw_import_source_channel_check;

ALTER TABLE raw_import
  ADD CONSTRAINT raw_import_source_channel_check
  CHECK (
    source_channel IN (
      'GMAIL',
      'UPLOAD',
      'CHATGPT',
      'BACKFILL',
      'SYNTHETIC'
    )
  );

COMMIT;
