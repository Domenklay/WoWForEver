CREATE TABLE IF NOT EXISTS forever_advancement_spells (
 guid BIGINT UNSIGNED NOT NULL,
 entry_id INT UNSIGNED NOT NULL,
 PRIMARY KEY (guid,entry_id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS forever_advancement_resources (
 guid BIGINT UNSIGNED NOT NULL,
 power_type INT UNSIGNED NOT NULL,
 current_value INT UNSIGNED NOT NULL,
 PRIMARY KEY (guid,power_type)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS forever_advancement_talents (
 guid BIGINT UNSIGNED NOT NULL,
 entry_id INT UNSIGNED NOT NULL,
 rank_value INT UNSIGNED NOT NULL,
 PRIMARY KEY (guid,entry_id)
) ENGINE=InnoDB;
