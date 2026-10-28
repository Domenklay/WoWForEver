-- DRAFT: account-wide unlocks and character-level selection.
-- Not executed automatically. Use auth/characters database mapping after validation.
CREATE TABLE IF NOT EXISTS encyclopedia_appearance (
  appearance_id INT UNSIGNED NOT NULL PRIMARY KEY,
  code VARCHAR(64) NOT NULL UNIQUE,
  display_id INT UNSIGNED DEFAULT NULL,
  name VARCHAR(128) NOT NULL,
  source_type ENUM('achievement','vendor','event','default') NOT NULL,
  source_id BIGINT UNSIGNED DEFAULT NULL,
  price_currency VARCHAR(32) DEFAULT NULL,
  price_amount BIGINT UNSIGNED DEFAULT NULL,
  enabled TINYINT(1) NOT NULL DEFAULT 0
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS encyclopedia_appearance_unlock (
  account_id BIGINT UNSIGNED NOT NULL,
  appearance_id INT UNSIGNED NOT NULL,
  unlocked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (account_id, appearance_id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS encyclopedia_appearance_selection (
  character_guid BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  appearance_id INT UNSIGNED NOT NULL
) ENGINE=InnoDB;
-- Purchases must be server-authoritative, atomic and verified against balance.
-- No real-money purchasing is implemented or implied.
