-- 001_dates_and_indexes.sql (WO-002): stored DATE columns beside the text dates, plus the
-- search and market indexes. Run once, locally, by an admin; never in CI or by the app
-- (idx_reader is SELECT-only). Idempotent: each step checks information_schema; a missing
-- source column is skipped with a note. A non-YYYY-MM-DD prefix becomes NULL, not an error.
--   mysql -u <admin> -p idx_exchange < scripts/migrations/001_dates_and_indexes.sql

-- The dumps carry legacy zero-date defaults (for example rets_property.active_check) that
-- strict mode rejects when a table is rebuilt, so this session drops the two zero-date
-- flags. Existing data is untouched; the mode is restored at the end.
SET @idx_old_sql_mode = @@SESSION.sql_mode;
SET SESSION sql_mode = REPLACE(REPLACE(@@SESSION.sql_mode, 'NO_ZERO_DATE', ''), 'NO_ZERO_IN_DATE', '');

DELIMITER $$

-- idx_add_date_column(table, source text column, new column): adds a STORED generated
-- DATE column parsed from the first 10 characters of the source. Skips, with a note row,
-- when the source is missing or the new column already exists.
DROP PROCEDURE IF EXISTS idx_add_date_column $$
CREATE PROCEDURE idx_add_date_column(IN t VARCHAR(64), IN src VARCHAR(64), IN dst VARCHAR(64))
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = t AND COLUMN_NAME = src)
     AND NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = t AND COLUMN_NAME = dst) THEN
    SET @sql = CONCAT('ALTER TABLE `', t, '` ADD COLUMN `', dst, '` DATE GENERATED ALWAYS AS ',
                      '(STR_TO_DATE(LEFT(`', src, '`, 10), ''%Y-%m-%d'')) STORED');
    PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
    SELECT CONCAT('added ', t, '.', dst) AS note;
  ELSE
    SELECT CONCAT('skipped ', t, '.', dst, ' (source missing or column present)') AS note;
  END IF;
END $$

-- idx_add_index(table, column, index name, prefix length): creates a one-column index,
-- on the first prefix_len characters when prefix_len > 0 (needed for text columns).
-- Skips, with a note row, when the column is missing, the index name already exists, or
-- another index already starts with that column (the active table ships with several).
DROP PROCEDURE IF EXISTS idx_add_index $$
CREATE PROCEDURE idx_add_index(IN t VARCHAR(64), IN col VARCHAR(64), IN idx VARCHAR(64), IN prefix_len INT)
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = t AND COLUMN_NAME = col)
     AND NOT EXISTS (SELECT 1 FROM information_schema.STATISTICS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = t AND INDEX_NAME = idx)
     AND NOT EXISTS (SELECT 1 FROM information_schema.STATISTICS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = t
               AND COLUMN_NAME = col AND SEQ_IN_INDEX = 1) THEN
    IF prefix_len > 0 THEN
      SET @sql = CONCAT('CREATE INDEX `', idx, '` ON `', t, '` (`', col, '`(', prefix_len, '))');
    ELSE
      SET @sql = CONCAT('CREATE INDEX `', idx, '` ON `', t, '` (`', col, '`)');
    END IF;
    PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
    SELECT CONCAT('created ', idx) AS note;
  ELSE
    SELECT CONCAT('skipped ', idx, ' (column missing or index present)') AS note;
  END IF;
END $$

DELIMITER ;

-- california_sold (closed transactions; dates are text, counts are doubles): adds DATE
-- columns for close, contract, and listing dates, and indexes on close date, city, postal
-- code, subtype, and ListingKey. Dumps differ in columns, so a missing one is skipped
-- with a note rather than failing the run.
CALL idx_add_date_column('california_sold', 'CloseDate', 'close_date_d');
CALL idx_add_date_column('california_sold', 'PurchaseContractDate', 'purchase_contract_date_d');
CALL idx_add_date_column('california_sold', 'ListingContractDate', 'listing_contract_date_d');
CALL idx_add_index('california_sold', 'close_date_d', 'ix_sold_close_date', 0);
CALL idx_add_index('california_sold', 'City', 'ix_sold_city', 64);
CALL idx_add_index('california_sold', 'PostalCode', 'ix_sold_postal', 10);
CALL idx_add_index('california_sold', 'PropertySubType', 'ix_sold_subtype', 40);
CALL idx_add_index('california_sold', 'ListingKey', 'ix_sold_listing_key', 0);

-- rets_property (active listings, IDX legacy names): adds DATE columns for the listing
-- contract date and modification time, and indexes on city, zip, subtype, price, and
-- listing id. As above, a column missing from the dump is skipped with a note.
CALL idx_add_date_column('rets_property', 'ListingContractDate', 'listing_contract_date_d');
CALL idx_add_date_column('rets_property', 'ModificationTimestamp', 'modification_d');
CALL idx_add_index('rets_property', 'L_City', 'ix_rets_city', 64);
CALL idx_add_index('rets_property', 'L_Zip', 'ix_rets_zip', 10);
CALL idx_add_index('rets_property', 'L_Type_', 'ix_rets_subtype', 40);
CALL idx_add_index('rets_property', 'L_SystemPrice', 'ix_rets_price', 0);
CALL idx_add_index('rets_property', 'L_ListingID', 'ix_rets_listing_id', 20);

-- Remove the helper procedures so the migration leaves only columns and indexes behind.
DROP PROCEDURE IF EXISTS idx_add_date_column;
DROP PROCEDURE IF EXISTS idx_add_index;
SET SESSION sql_mode = @idx_old_sql_mode;
