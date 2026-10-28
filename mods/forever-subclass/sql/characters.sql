-- Namespaced schema for the Forever adapter. Apply with the local backup installer.

CREATE TABLE IF NOT EXISTS `forever_character_class_progress` (
  `guid` BIGINT UNSIGNED NOT NULL,
  `class_id` TINYINT UNSIGNED NOT NULL,
  `class_level` TINYINT UNSIGNED NOT NULL DEFAULT 1,
  `class_xp` BIGINT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (`guid`, `class_id`),
  INDEX `idx_fccp_guid` (`guid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `forever_character_subclass_state` (
  `guid` BIGINT UNSIGNED NOT NULL,
  `primary_class_id` TINYINT UNSIGNED NOT NULL,
  `active_subclass_id` TINYINT UNSIGNED NULL,
  `xp_target_class_id` TINYINT UNSIGNED NULL,
  PRIMARY KEY (`guid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `forever_character_subclass_spells` (
  `guid` BIGINT UNSIGNED NOT NULL,
  `spell_id` INT UNSIGNED NOT NULL,
  PRIMARY KEY (`guid`, `spell_id`),
  INDEX `idx_fcss_guid` (`guid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `forever_character_subclass_resources` (
  `guid` BIGINT UNSIGNED NOT NULL,
  `power_type` TINYINT UNSIGNED NOT NULL,
  `current_value` INT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (`guid`, `power_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `forever_character_subclass_talents` (
  `guid` BIGINT UNSIGNED NOT NULL,
  `class_id` TINYINT UNSIGNED NOT NULL,
  `talent_id` SMALLINT UNSIGNED NOT NULL,
  `rank` TINYINT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (`guid`, `class_id`, `talent_id`),
  INDEX `idx_fcst_guid_class` (`guid`, `class_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Freepick v1 has an independent purchase ledger. No legacy spells/classes are imported.
CREATE TABLE IF NOT EXISTS `forever_character_freepick_state` (
  `guid` BIGINT UNSIGNED NOT NULL,
  `primary_class_id` TINYINT UNSIGNED NOT NULL,
  `catalogue_class_id` TINYINT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (`guid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `forever_character_freepick_spells` (
  `guid` BIGINT UNSIGNED NOT NULL,
  `spell_id` INT UNSIGNED NOT NULL,
  PRIMARY KEY (`guid`, `spell_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `forever_character_freepick_resources` (
  `guid` BIGINT UNSIGNED NOT NULL,
  `power_type` TINYINT UNSIGNED NOT NULL,
  `current_value` INT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (`guid`, `power_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
