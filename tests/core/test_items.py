"""物品表锚点测试 — engine_id = mod 文件行号 - 1, 不能再 off-by-one."""

import pytest

from core.items import (
    ITEMS,
    ItemCategory,
    UNSET,
    get_item_category,
    get_item_name,
    is_equippable,
    item_combat_bonus,
    item_desc,
    item_effect,
    item_table_entry,
)


def test_known_anchors():
    """从 mod 秘籍 + 存档锚点反推的 ID, 不能再漂."""
    # 存档锚点: 孙悟空 Hand=128 → '如意双截棍'
    assert get_item_name(128) == '如意双截棍'
    # cheat asyourwish → '如意棒'
    assert get_item_name(199) == '如意棒'
    # cheat gundamisgundam 给 '光剑'
    assert get_item_name(200) == '光剑'
    # ID 0 = 默认普通帽子 (旧表漏掉, 现在补上)
    assert get_item_name(0) == '普通帽子'


def test_unset_and_missing():
    assert get_item_name(UNSET) == "无"
    assert get_item_name(-1) == "无"
    # ID 354 在 mod 表里空缺 (引擎未用)
    assert get_item_name(354) == "未知#354"
    assert get_item_name(99999) == "未知#99999"


def test_category_boundaries():
    """5 段类别的边界点必须落在正确分类里."""
    assert get_item_category(0) == ItemCategory.HAT          # 帽子段起点
    assert get_item_category(64) == ItemCategory.HAT         # 帽子段末
    assert get_item_category(65) == ItemCategory.CLOTHES     # 衣服段起点
    assert get_item_category(120) == ItemCategory.CLOTHES    # 衣服段末
    assert get_item_category(121) == ItemCategory.WEAPON     # 武器段起点
    assert get_item_category(200) == ItemCategory.WEAPON     # 武器段末 (光剑)
    assert get_item_category(201) == ItemCategory.ACCESSORY  # 首饰段起点
    assert get_item_category(298) == ItemCategory.ACCESSORY  # 首饰段末
    assert get_item_category(299) == ItemCategory.CONSUMABLE # 消耗品段


def test_total_count():
    """表项数固定 355 项 (mod 文件 356 - 1 个空白 ID 354)."""
    assert len(ITEMS) == 355


# ---------------------------------------------------------------------------
# 原版真实数值 (源自 FlyingSB.exe 物品表; 缺 assets 自动 skip)
# ---------------------------------------------------------------------------
_have_table = item_table_entry(124) is not None


@pytest.mark.skipif(not _have_table, reason="缺 assets/items_table.json")
def test_equip_stats_real():
    """装备属性取自原版表: 攻击/防御/五维加成, 归属由反汇编确认."""
    assert item_combat_bonus(1) == {"def": 2}                    # 草帽 防+2
    assert item_combat_bonus(124) == {"atk": 300}                # 双截棍 攻+300
    assert item_combat_bonus(128) == {"atk": 960}                # 如意双截棍 攻+960
    assert item_combat_bonus(208) == {"pow": -10, "wis": 30, "atk": -50}  # 魔法师头饰
    assert item_combat_bonus(213) == {"wis": 3, "agi": 8, "atk": 470,
                                      "def": 100, "luk": 5}       # 君子剑
    # 消耗品不可装备 → 无加成
    assert item_combat_bonus(299) == {}
    assert not is_equippable(299)
    assert is_equippable(124)


@pytest.mark.skipif(not _have_table, reason="缺 assets/items_table.json")
def test_item_effect_real():
    """回复品效果取自原版 (type=14); 全回复记 9999."""
    assert item_effect(299) == (50, 0)       # 恢复药 HP+50
    assert item_effect(300) == (300, 0)      # 良药 HP+300
    assert item_effect(301) == (9999, 0)     # 优药 HP 全回
    assert item_effect(302) == (0, 50)       # 药草 MP+50
    assert item_effect(303) == (0, 150)      # 良药 MP+150
    assert item_effect(304) == (0, 9999)     # 优药 MP 全回
    assert item_effect(305) == (9999, 9999)  # 仙桃 HP/MP 全回
    # 非回复类 (船票) 无效果
    assert item_effect(343) == (0, 0)


@pytest.mark.skipif(not _have_table, reason="缺 assets/items_table.json")
def test_item_desc_real():
    """描述来自原版 +0x44 字符串."""
    assert "龙宫宝物" in item_desc(124)
    assert item_desc(299).startswith("HP")
