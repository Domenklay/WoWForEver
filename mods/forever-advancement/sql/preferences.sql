-- Additive, independent of legacy progression tables. Existing characters default to 90/10.
CREATE TABLE IF NOT EXISTS forever_advancement_preferences (
 guid BIGINT UNSIGNED NOT NULL,
 xp_enabled TINYINT UNSIGNED NOT NULL DEFAULT 1,
 xp_remainder TINYINT UNSIGNED NOT NULL DEFAULT 0,
 PRIMARY KEY (guid)
) ENGINE=InnoDB;
