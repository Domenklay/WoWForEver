ForeverEncyclopediaTalentCatalog = {
    branches = {
        protection = { name = "Защита", icon = "Interface\\Icons\\Spell_Holy_PowerWordShield", color = {0.76, 0.62, 0.30} },
        healing    = { name = "Исцеление", icon = "Interface\\Icons\\Spell_Holy_Heal", color = {0.44, 0.78, 0.46} },
        support    = { name = "Усиление", icon = "Interface\\Icons\\Spell_Arcane_Arcane01", color = {0.65, 0.52, 0.86} },
        wisdom     = { name = "Мудрость", icon = "Interface\\Icons\\INV_Misc_Book_11", color = {0.35, 0.62, 0.92} },
        knowledge  = { name = "Познание", icon = "Interface\\Icons\\INV_Misc_Book_09", color = {0.86, 0.66, 0.28} },
    },
    order = { "protection", "healing", "support", "wisdom", "knowledge" },
    nodes = {
        -- Protection
        { key="aegis_unlock", branch="protection", name="Охранная печать", max=1, base=3, step=0, quad=0, tier=1, col=2, icon="Interface\\Icons\\Spell_Holy_PowerWordShield", desc="Открывает автоматический щит Живой книги. Базовый барьер рассчитан как заметная, но не заменяющая лекаря защита." },
        { key="aegis_strength", branch="protection", name="Плотная формула", max=5, base=2, step=2, quad=0, tier=2, col=1, req="aegis_unlock", reqRank=1, icon="Interface\\Icons\\Spell_Holy_BlessingOfProtection", desc="Усиливает размер щита. Ранние ранги дешёвые, чтобы защита ощущалась почти сразу." },
        { key="aegis_efficiency", branch="protection", name="Экономная вязь", max=5, base=3, step=3, quad=0, tier=2, col=2, req="aegis_unlock", reqRank=1, icon="Interface\\Icons\\Spell_Holy_SealOfWisdom", desc="Снижает расход маны на защитную способность." },
        { key="aegis_reflex", branch="protection", name="Быстрая сноска", max=5, base=5, step=5, quad=0, tier=2, col=3, req="aegis_unlock", reqRank=1, icon="Interface\\Icons\\Ability_Paladin_ShieldoftheTemplar", desc="Постепенно сокращает перезарядку щита." },
        { key="aegis_group", branch="protection", name="Общая глава", max=1, base=60, step=0, quad=0, tier=3, col=1, req="aegis_strength", reqRank=3, icon="Interface\\Icons\\Spell_Holy_DevotionAura", desc="Позволяет книге выбирать для щита союзника в малой группе до 4 игроков." },
        { key="aegis_overcharge", branch="protection", name="Усиленная обложка", max=4, base=35, step=20, quad=5, tier=3, col=3, req="aegis_strength", reqRank=5, icon="Interface\\Icons\\Spell_Holy_ArdentDefender", desc="Позднее усиление барьера. Итоговый щит никогда не превышает 30% максимального HP цели." },
        { key="aegis_mastery", branch="protection", name="Мастерство хранителя", max=15, base=100, step=20, quad=1, tier=4, col=2, req="aegis_overcharge", reqRank=4, icon="Interface\\Icons\\INV_Misc_Book_07", desc="Дорогая долгосрочная специализация с очень небольшой отдачей за ранг. Предназначена как sink, а не источник бесконечной силы." },

        -- Healing
        { key="mend_unlock", branch="healing", name="Целительная пометка", max=1, base=3, step=0, quad=0, tier=1, col=2, icon="Interface\\Icons\\Spell_Holy_Heal", desc="Открывает реактивное лечение Живой книги." },
        { key="mend_power", branch="healing", name="Полезная поправка", max=5, base=2, step=2, quad=0, tier=2, col=1, req="mend_unlock", reqRank=1, icon="Interface\\Icons\\Spell_Holy_GreaterHeal", desc="Увеличивает объём обычного лечения. Базовый предел одного применения — 25% максимального HP." },
        { key="mend_efficiency", branch="healing", name="Краткая формула", max=5, base=3, step=3, quad=0, tier=2, col=2, req="mend_unlock", reqRank=1, icon="Interface\\Icons\\Spell_Holy_Renew", desc="Снижает расход маны на лечение." },
        { key="mend_reflex", branch="healing", name="Мгновенная закладка", max=5, base=5, step=5, quad=0, tier=2, col=3, req="mend_unlock", reqRank=1, icon="Interface\\Icons\\Spell_Holy_FlashHeal", desc="Сокращает перезарядку лечения, но не позволяет книге спамить им без ограничений маны." },
        { key="mend_group", branch="healing", name="Полевая редакция", max=1, base=60, step=0, quad=0, tier=3, col=1, req="mend_power", reqRank=3, icon="Interface\\Icons\\Spell_Holy_PrayerOfHealing02", desc="Разрешает выбирать раненого союзника в малой группе." },
        { key="mend_deep", branch="healing", name="Глубокое исправление", max=3, base=40, step=25, quad=5, tier=3, col=3, req="mend_power", reqRank=5, icon="Interface\\Icons\\Spell_Holy_HolyGuidance", desc="Поднимает предельный объём одного лечения вплоть до абсолютного потолка 40% HP." },
        { key="mend_mastery", branch="healing", name="Мастерство целителя", max=15, base=100, step=20, quad=1, tier=4, col=2, req="mend_deep", reqRank=3, icon="Interface\\Icons\\INV_Misc_Book_05", desc="Поздняя специализация с убывающей выгодой; не заменяет полноценного лекаря." },

        -- Support
        { key="insight_unlock", branch="support", name="Тактическая подсказка", max=1, base=5, step=0, quad=0, tier=1, col=2, icon="Interface\\Icons\\Spell_Arcane_Arcane01", desc="Открывает способность поддержки: короткую PvE-подсказку без прямого урона." },
        { key="insight_duration", branch="support", name="Развёрнутое примечание", max=5, base=3, step=3, quad=0, tier=2, col=1, req="insight_unlock", reqRank=1, icon="Interface\\Icons\\Spell_Arcane_Blink", desc="Увеличивает длительность полезного эффекта поддержки." },
        { key="insight_efficiency", branch="support", name="Сжатый текст", max=5, base=4, step=4, quad=0, tier=2, col=2, req="insight_unlock", reqRank=1, icon="Interface\\Icons\\Spell_Arcane_ManaTap", desc="Снижает расход маны на поддержку." },
        { key="insight_reflex", branch="support", name="Быстрый совет", max=5, base=8, step=6, quad=1, tier=2, col=3, req="insight_unlock", reqRank=1, icon="Interface\\Icons\\Spell_Arcane_ArcaneResilience", desc="Сокращает перезарядку поддержки." },
        { key="insight_group", branch="support", name="Совет группе", max=1, base=75, step=0, quad=0, tier=3, col=1, req="insight_duration", reqRank=3, icon="Interface\\Icons\\Spell_Holy_PrayerOfSpirit", desc="Позволяет книге использовать поддержку на участнике малой группы." },
        { key="insight_cleanse", branch="support", name="Исправление ошибки", max=1, base=150, step=0, quad=0, tier=3, col=3, req="insight_group", reqRank=1, icon="Interface\\Icons\\Spell_Holy_DispelMagic", desc="Поздняя утилита: книга сможет снимать ограниченный набор обычных PvE-негативных эффектов." },
        { key="insight_mastery", branch="support", name="Мастерство советника", max=15, base=110, step=22, quad=1, tier=4, col=2, req="insight_cleanse", reqRank=1, icon="Interface\\Icons\\INV_Misc_Book_06", desc="Долгая специализация с небольшой отдачей на ранг." },

        -- Wisdom
        { key="mana_capacity", branch="wisdom", name="Расширенный переплёт", max=10, base=2, step=2, quad=0, tier=1, col=2, icon="Interface\\Icons\\INV_Enchant_EssenceAstralLarge", desc="+10 максимальной маны книги за ранг. Первый ранг доступен почти сразу." },
        { key="mana_combat_regen", branch="wisdom", name="Боевая концентрация", max=5, base=5, step=5, quad=0, tier=2, col=1, req="mana_capacity", reqRank=2, icon="Interface\\Icons\\Spell_Nature_MoonGlow", desc="Улучшает медленное восстановление маны в бою от базовых +1/5 сек." },
        { key="mana_rest_regen", branch="wisdom", name="Тихое чтение", max=5, base=3, step=3, quad=0, tier=2, col=3, req="mana_capacity", reqRank=2, icon="Interface\\Icons\\Spell_Nature_Tranquility", desc="Ускоряет восстановление маны вне боя от базовых +5/5 сек." },
        { key="mana_reserve", branch="wisdom", name="Неприкосновенный резерв", max=5, base=10, step=8, quad=1, tier=3, col=1, req="mana_capacity", reqRank=5, icon="Interface\\Icons\\Spell_Arcane_MindMastery", desc="Оставляет часть маны для экстренных защитных реакций." },
        { key="mana_conservation", branch="wisdom", name="Экономия чернил", max=5, base=20, step=15, quad=2, tier=3, col=2, req="mana_reserve", reqRank=3, icon="Interface\\Icons\\INV_Enchant_DustIllusion", desc="Даёт ограниченную экономию маны, не создавая бесконечного ресурса." },
        { key="mana_overflow", branch="wisdom", name="Избыточный запас", max=5, base=60, step=30, quad=3, tier=3, col=3, req="mana_conservation", reqRank=5, icon="Interface\\Icons\\Spell_Arcane_ArcanePotency", desc="Позднее улучшение запаса и восстановления; эффективность жёстко ограничена." },
        { key="wisdom_mastery", branch="wisdom", name="Мастерство мудреца", max=15, base=100, step=20, quad=1, tier=4, col=2, req="mana_overflow", reqRank=5, icon="Interface\\Icons\\INV_Misc_Book_10", desc="Дорогие поздние ранги. Каждый даёт лишь +2 максимальной маны и небольшие будущие удобства." },

        -- Knowledge
        { key="identify_name", branch="knowledge", name="Название и вид", max=1, base=1, step=0, quad=0, tier=1, col=2, icon="Interface\\Icons\\INV_Misc_Note_01", desc="Всего за 1 очко книга начинает показывать имя и тип даже ещё не встреченного существа." },
        { key="identify_rank", branch="knowledge", name="Класс угрозы", max=1, base=3, step=0, quad=0, tier=2, col=1, req="identify_name", reqRank=1, icon="Interface\\Icons\\Ability_Hunter_SniperShot", desc="Показывает классификацию: обычное, элита, редкое, босс." },
        { key="identify_stats", branch="knowledge", name="Полевые параметры", max=1, base=5, step=0, quad=0, tier=2, col=3, req="identify_rank", reqRank=1, icon="Interface\\Icons\\INV_Misc_Spyglass_03", desc="Показывает диапазон уровней и базовые параметры записи." },
        { key="identify_abilities", branch="knowledge", name="Разбор способностей", max=1, base=10, step=0, quad=0, tier=3, col=1, req="identify_stats", reqRank=1, icon="Interface\\Icons\\INV_Misc_Book_08", desc="Открывает раздел известных способностей существа." },
        { key="identify_resists", branch="knowledge", name="Слабости и защиты", max=1, base=20, step=0, quad=0, tier=3, col=2, req="identify_abilities", reqRank=1, icon="Interface\\Icons\\Spell_Holy_ResistanceAura", desc="Открывает сопротивления и значимые защитные особенности." },
        { key="identify_loot", branch="knowledge", name="Ценный лут", max=1, base=35, step=0, quad=0, tier=3, col=3, req="identify_resists", reqRank=1, icon="Interface\\Icons\\INV_Misc_Bag_10", desc="Открывает полезную часть таблицы добычи, без засорения окна каждым серым предметом." },
        { key="identify_locations", branch="knowledge", name="Ареал обитания", max=1, base=60, step=0, quad=0, tier=4, col=1, req="identify_loot", reqRank=1, icon="Interface\\Icons\\INV_Misc_Map_01", desc="Показывает зоны, где запись реально встречается на сервере." },
        { key="identify_rares", branch="knowledge", name="Редкие примечания", max=1, base=120, step=0, quad=0, tier=4, col=3, req="identify_locations", reqRank=1, icon="Interface\\Icons\\INV_Misc_Map_07", desc="Выделяет редкие и особые варианты, если они есть в данных мира." },
        { key="knowledge_mastery", branch="knowledge", name="Мастерство архивариуса", max=15, base=90, step=18, quad=1, tier=5, col=2, req="identify_rares", reqRank=1, icon="Interface\\Icons\\INV_Misc_Book_04", desc="Долгосрочный архивный sink: дополнительные заметки, удобство поиска и косметические бонусы без роста боевой мощи." },
    },
    appearances = {
        { key="living_book", name="Живая книга", threshold=0, creature=171120, source="Базовый облик" },
        { key="archivist", name="Архивариус", threshold=100, creature=205781, source="100 накопленных знаний" },
        { key="knowledge_spirit", name="Дух знаний", threshold=500, creature=161896, source="500 накопленных знаний" },
        { key="small_construct", name="Малый конструкт", threshold=1500, creature=183783, source="1500 накопленных знаний" },
        { key="runekeeper", name="Хранитель рун", threshold=5000, creature=130946, source="5000 накопленных знаний" },
    },
}

function ForeverEncyclopediaTalentCost(node, currentRank)
    local r = tonumber(currentRank) or 0
    return (node.base or 0) + (node.step or 0) * r + (node.quad or 0) * r * r
end
