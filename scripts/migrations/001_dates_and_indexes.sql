-- 001_dates_and_indexes.sql (WO-002). Applied once, locally, by an admin user; never in CI
-- and never by the application (idx_reader is SELECT-only).
--
-- Adds real DATE columns next to the text date columns and the indexes the search and
-- market tools need. Idempotent: every step checks information_schema first, so running it
-- twice is safe, and a column that does not exist in a dump is skipped with a note.
-- The generated columns use STR_TO_DATE, which yields NULL for a value that is not a clean
-- YYYY-MM-DD prefix instead of failing the whole statement.
--
--   mysql -u <admin> -p idx_exchange < scripts/migrations/001_dates_and_indexes.sql

DELIMITER $$

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

DROP PROCEDURE IF EXISTS idx_add_index $$
CREATE PROCEDURE idx_add_index(IN t VARCHAR(64), IN col VARCHAR(64), IN idx VARCHAR(64), IN prefix_len INT)
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = t AND COLUMN_NAME = col)
     AND NOT EXISTS (SELECT 1 FROM information_schema.STATISTICS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = t AND INDEX_NAME = idx) THEN
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

-- california_sold: closed transactions. Dates are text; counts are doubles.
CALL idx_add_date_column('california_sold', 'CloseDate', 'close_date_d');
CALL idx_add_date_column('california_sold', 'PurchaseContractDate', 'purchase_contract_date_d');
CALL idx_add_date_column('california_sold', 'ListingContractDate', 'listing_contract_date_d');
CALL idx_add_index('california_sold', 'close_date_d', 'ix_sold_close_date', 0);
CALL idx_add_index('california_sold', 'City', 'ix_sold_city', 64);
CALL idx_add_index('california_sold', 'PostalCode', 'ix_sold_postal', 10);
CALL idx_add_index('california_sold', 'PropertySubType', 'ix_sold_subtype', 40);
CALL idx_add_index('california_sold', 'ListingKey', 'ix_sold_listing_key', 0);

-- rets_property: active listings with IDX legacy names.
CALL idx_add_date_column('rets_property', 'ListingContractDate', 'listing_contract_date_d');
CALL idx_add_date_column('rets_property', 'ModificationTimestamp', 'modification_d');
CALL idx_add_index('rets_property', 'L_City', 'ix_rets_city', 64);
CALL idx_add_index('rets_property', 'L_Zip', 'ix_rets_zip', 10);
CALL idx_add_index('rets_property', 'L_Type_', 'ix_rets_subtype', 40);
CALL idx_add_index('rets_property', 'L_SystemPrice', 'ix_rets_price', 0);
CALL idx_add_index('rets_property', 'L_ListingID', 'ix_rets_listing_id', 20);

DROP PROCEDURE IF EXISTS idx_add_date_column;
DROP PROCEDURE IF EXISTS idx_add_index;
