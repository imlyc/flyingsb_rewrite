"""物品表锚点测试 — engine_id = mod 文件行号 - 1, 不能再 off-by-one."""

import pytest

from core.items import ITEMS, ItemCategory, UNSET, get_item_category, get_item_name


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
