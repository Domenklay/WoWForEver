CREATE TABLE IF NOT EXISTS `forever_encyclopedia_appearance_selection` (
  `character_guid` BIGINT UNSIGNED NOT NULL,
  `appearance_key` VARCHAR(32) NOT NULL DEFAULT 'living_book',
  `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`character_guid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
