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
