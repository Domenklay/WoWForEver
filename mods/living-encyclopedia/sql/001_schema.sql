-- DRAFT ONLY: run only after confirming DB placement/schema with TrinityCore forever.
-- Account-wide tables; do not apply to production without backup.
CREATE TABLE IF NOT EXISTS encyclopedia_account (
  account_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  knowledge_total BIGINT UNSIGNED NOT NULL DEFAULT 0,
  knowledge_spent BIGINT UNSIGNED NOT NULL DEFAULT 0,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT chk_encyclopedia_spent CHECK (knowledge_spent <= knowledge_total)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS encyclopedia_discovery (
  account_id BIGINT UNSIGNED NOT NULL,
  kind VARCHAR(24) NOT NULL,
  entry_id BIGINT UNSIGNED NOT NULL,
  reward_points INT UNSIGNED NOT NULL DEFAULT 0,
  discovered_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (account_id, kind, entry_id),
  KEY ix_encyclopedia_kind_entry (kind, entry_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS encyclopedia_talent (
  account_id BIGINT UNSIGNED NOT NULL,
  talent_key VARCHAR(64) NOT NULL,
  rank SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (account_id, talent_key)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS encyclopedia_character (
  character_guid BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  mana INT UNSIGNED NOT NULL DEFAULT 0,
  shield_enabled TINYINT(1) NOT NULL DEFAULT 1,
  heal_enabled TINYINT(1) NOT NULL DEFAULT 1,
  shield_threshold TINYINT UNSIGNED NOT NULL DEFAULT 80,
  heal_threshold TINYINT UNSIGNED NOT NULL DEFAULT 50,
  mana_reserve INT UNSIGNED NOT NULL DEFAULT 0,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;
