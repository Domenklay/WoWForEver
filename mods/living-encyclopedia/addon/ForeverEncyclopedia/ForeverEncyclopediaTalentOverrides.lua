-- Keep tooltip numbers synchronized with server/TalentRules.h and RuntimeV5.
-- Unfinished talents remain visible for planning, but cannot be purchased.
local catalog = ForeverEncyclopediaTalentCatalog
if not catalog or not catalog.nodes then return end

local implemented = {
    aegis_unlock=true, aegis_strength=true, aegis_efficiency=true,
    aegis_reflex=true, aegis_overcharge=true,
    mend_unlock=true, mend_power=true, mend_efficiency=true,
    mend_reflex=true, mend_deep=true,
    mana_capacity=true, mana_combat_regen=true, mana_rest_regen=true,
    mana_reserve=true, mana_overflow=true, wisdom_mastery=true,
    identify_name=true, identify_rank=true, identify_stats=true,
    identify_abilities=true,
}

local notes = {
    aegis_unlock = "Автоматический щит при получении PvE-урона и HP ниже выбранного порога (по умолчанию 80%).",
    aegis_strength = "Каждый ранг добавляет 2 процентных пункта к пределу щита; максимум 30% HP.",
    aegis_efficiency = "Каждый ранг добавляет 1 процентный пункт к щиту. Расход не снижается: 1 мана = 1 поглощение.",
    aegis_reflex = "Каждый ранг сокращает КД щита на 2 секунды, минимум 20 сек.",
    aegis_overcharge = "Каждый ранг добавляет 1 процентный пункт к пределу щита, максимум 30% HP.",
    mend_unlock = "Реактивное лечение при PvE-уроне и низком HP. По умолчанию порог 50% HP.",
    mend_power = "Каждый ранг усиливает исходное лечение на 10% до ограничений HP и маны.",
    mend_efficiency = "Каждый ранг повышает порог лечения на 4 процентных пункта (не выше 80%). Стоимость всегда 1 мана = 1 HP.",
    mend_reflex = "Каждый ранг сокращает КД лечения на 2 секунды, минимум 15 сек.",
    mend_deep = "Каждый ранг увеличивает предел лечения на 5 процентных пунктов, максимум 40% HP.",
    mana_capacity = "+10 к максимальной мане за ранг. Каждые 10 накопленных знаний отдельно дают +1 ману.",
    mana_combat_regen = "Базово +1 мана за 5 сек. в бою. Каждый ранг добавляет 0,2% от максимума за 5 сек.",
    mana_rest_regen = "Базово +5 маны за 5 сек. вне боя. Каждый ранг добавляет 0,2% от максимума за 5 сек.",
    mana_reserve = "Каждый ранг резервирует 5% максимальной маны для щита: лечение не может потратить этот запас.",
    mana_overflow = "+15 к максимальной мане за ранг. Не ускоряет процентную регенерацию.",
    wisdom_mastery = "+2 к максимальной мане за ранг. Поздняя специализация без бесконечного роста силы.",
    identify_name = "Показывает имя и тип существа из доступной серверной записи.",
    identify_rank = "Показывает категорию угрозы: обычное, элита, редкое, босс.",
    identify_stats = "Показывает уровни, семейство, школу урона и интервалы атак. HP/броня пока не индексируются.",
    identify_abilities = "Показывает активные заклинания из шаблона NPC и SmartAI; C++-скрипты пока не индексируются.",
}

for _, node in ipairs(catalog.nodes) do
    node.implemented = implemented[node.key] == true
    if node.implemented then
        node.desc = notes[node.key] or node.desc
    else
        node.desc = "В разработке. Серверный эффект ещё не подключён; новые покупки заблокированы. Ранее изученные ранги сохраняются."
    end
    if node.key == "mana_overflow" then
        -- Conservation is not implemented yet. Do not block real capacity growth behind it.
        node.req = "mana_capacity"
        node.reqRank = 10
    end
end

local function value(key, rank, ranks, maxMana)
    ranks = ranks or {}
    local function r(k)
        if key == k then return rank end
        return tonumber(ranks[k]) or 0
    end
    local shield = math.min(30, 12 + math.min(10, 2*r("aegis_strength"))
        + math.min(5, r("aegis_efficiency")) + math.min(4, r("aegis_overcharge")))
    if key:sub(1,6) == "aegis_" then
        if key == "aegis_unlock" and rank == 0 then return "Способность закрыта" end
        if key == "aegis_reflex" then
            return (30 - math.min(10, 2*rank)) .. " сек. КД щита"
        end
        if key == "aegis_group" or key == "aegis_mastery" then return "Не реализовано" end
        return shield .. "% HP — предел щита"
    end
    if key:sub(1,5) == "mend_" then
        if key == "mend_unlock" and rank == 0 then return "Способность закрыта" end
        if key == "mend_reflex" then return (25 - math.min(10, 2*rank)) .. " сек. КД лечения" end
        if key == "mend_power" then return (100 + math.min(5, rank)*10) .. "% силы исходного лечения" end
        if key == "mend_efficiency" then return math.min(80, 50 + 4*rank) .. "% HP — порог по умолчанию" end
        if key == "mend_deep" then return math.min(40, 25 + 5*rank) .. "% HP — предел лечения" end
        if key == "mend_group" or key == "mend_mastery" then return "Не реализовано" end
        return (25 + math.min(15, 5*r("mend_deep"))) .. "% HP — предел лечения"
    end
    if key == "mana_capacity" then return "+" .. (10*rank) .. " к максимальной мане" end
    if key == "mana_overflow" then return "+" .. (15*rank) .. " к максимальной мане" end
    if key == "wisdom_mastery" then return "+" .. (2*rank) .. " к максимальной мане" end
    if key == "mana_combat_regen" or key == "mana_rest_regen" then
        local base = key == "mana_combat_regen" and 1 or 5
        local pct = string.format("%.1f", math.min(rank, 5)*0.2):gsub("%.", ",")
        return "+" .. base .. " маны + " .. pct .. "% максимума/5 сек."
    end
    if key == "mana_reserve" then
        local pct = math.min(25, rank*5)
        local amount = math.floor((tonumber(maxMana) or 100) * pct / 100)
        return pct .. "% (" .. amount .. " маны) только для щита"
    end
    if key:sub(1,9) == "identify_" then
        return rank > 0 and "Раздел открыт" or "Раздел закрыт"
    end
    return "Не реализовано"
end

function catalog.EffectPreview(node, rank, ranks, maxMana)
    if not node.implemented then return "Не реализовано", "Покупка недоступна" end
    local current = value(node.key, rank, ranks, maxMana)
    local nextRank = math.min(node.max, rank + 1)
    local nextValue = nextRank == rank and "Максимальный ранг" or value(node.key, nextRank, ranks, maxMana)
    return current, nextValue
end
