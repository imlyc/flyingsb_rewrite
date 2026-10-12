"""Inventory 模型 + 存档 trailer 往返测试."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from core.inventory import Inventory
from core.items import ItemCategory, get_item_category
from core.save_manager import load_save, new_game_save, save_save


def test_add_remove_count():
    inv = Inventory()
    inv.add(299, 3)
    assert inv.count(299) == 3
    assert inv.has(299, 2)
    assert not inv.has(299, 4)
    assert inv.remove(299, 2)
    assert inv.count(299) == 1
    assert inv.remove(299, 1)
    assert inv.count(299) == 0          # 归零后自动移除
    assert not inv.remove(299, 1)       # 不足返回 False


def test_categories():
    inv = Inventory({299: 2, 124: 1, 1: 1})   # 消耗品/武器/帽子
    cons = dict(inv.consumables())
    assert cons.get(299) == 2
    eq = dict(inv.equipment())
    assert 124 in eq and 1 in eq
    assert 299 not in eq


def test_serialization_roundtrip():
    inv = Inventory({299: 3, 300: 2, 305: 1, 124: 1})
    data = inv.to_bytes()
    assert data.startswith(b"INV1")
    back = Inventory.from_bytes(data)
    assert back.slots == inv.slots


def test_new_game_has_starter_inventory():
    from core import character_data
    from core.party import NAME_TO_SLOT
    save = new_game_save()
    assert save.inventory.count(299) == 3
    assert save.inventory.count(300) == 2
    # 美娜初始装备取自 exe 角色定义表 (Body=65 薄衣 / Hand=129); 缺 assets 时回退占位
    expected_hand = 129 if character_data.records() else 124
    assert save.characters[NAME_TO_SLOT["美娜"]].Hand == expected_hand


def test_save_load_roundtrip():
    save = new_game_save()
    save.inventory.add(339, 5)
    p = os.path.join(tempfile.gettempdir(), "inv_rt.dat")
    save_save(save, p)
    back = load_save(p)
    assert back.inventory.slots == save.inventory.slots
    # 原版存档无 trailer → 背包为空
    if not Path("saveData/Save1.dat").exists():
        pytest.skip("缺 saveData/Save1.dat (原版存档不入库)")
    real = load_save("saveData/Save1.dat")
    assert real.inventory.total() == 0
