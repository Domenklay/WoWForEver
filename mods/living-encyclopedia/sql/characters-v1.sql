CREATE TABLE IF NOT EXISTS `forever_encyclopedia_discovery` (
  `account_id` INT UNSIGNED NOT NULL,
  `kind` TINYINT UNSIGNED NOT NULL,
  `entry` INT UNSIGNED NOT NULL,
  `first_map` INT UNSIGNED NOT NULL DEFAULT 0,
  `first_zone` INT UNSIGNED NOT NULL DEFAULT 0,
  `first_seen` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`account_id`,`kind`,`entry`),
  KEY `idx_forever_ency_account_kind` (`account_id`,`kind`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `forever_encyclopedia_account` (
  `account_id` INT UNSIGNED NOT NULL,
  `knowledge_total` BIGINT UNSIGNED NOT NULL DEFAULT 0,
  `knowledge_spent` BIGINT UNSIGNED NOT NULL DEFAULT 0,
  `discoveries` INT UNSIGNED NOT NULL DEFAULT 0,
  `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`account_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `forever_encyclopedia_talent` (
  `account_id` INT UNSIGNED NOT NULL,
  `talent_key` VARCHAR(64) NOT NULL,
  `rank` SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (`account_id`,`talent_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `forever_encyclopedia_character` (
  `character_guid` BIGINT UNSIGNED NOT NULL,
  `mana` INT UNSIGNED NOT NULL DEFAULT 0,
  `shield_enabled` TINYINT UNSIGNED NOT NULL DEFAULT 1,
  `heal_enabled` TINYINT UNSIGNED NOT NULL DEFAULT 1,
  `shield_threshold` TINYINT UNSIGNED NOT NULL DEFAULT 80,
  `heal_threshold` TINYINT UNSIGNED NOT NULL DEFAULT 50,
  `mana_reserve` INT UNSIGNED NOT NULL DEFAULT 0,
  `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`character_guid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
