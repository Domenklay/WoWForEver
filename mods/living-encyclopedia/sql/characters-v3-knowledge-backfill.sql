-- Idempotent backfill for accounts that discovered encyclopedia records before
-- knowledge rewards were enabled.  Discovery kinds in the live server schema:
-- 1 creature = 1 point, 2 item = 1 point, 3 zone = 3 points.
-- GREATEST keeps any newer/non-discovery rewards and makes repeated installs safe.
INSERT INTO `forever_encyclopedia_account`
    (`account_id`,`knowledge_total`,`knowledge_spent`,`discoveries`)
SELECT
    `account_id`,
    SUM(CASE `kind`
        WHEN 1 THEN 1
        WHEN 2 THEN 1
        WHEN 3 THEN 3
        ELSE 0
    END) AS `historical_knowledge`,
    0,
    COUNT(*)
FROM `forever_encyclopedia_discovery`
GROUP BY `account_id`
ON DUPLICATE KEY UPDATE
    `knowledge_total` = GREATEST(`knowledge_total`, VALUES(`knowledge_total`)),
    `discoveries` = GREATEST(`discoveries`, VALUES(`discoveries`));
