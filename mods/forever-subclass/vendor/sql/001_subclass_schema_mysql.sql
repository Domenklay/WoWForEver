-- Prototype schema for MySQL/MariaDB. Names are deliberately namespaced.
-- Do not merge directly into a production character DB until the actual Forever core is selected.

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
