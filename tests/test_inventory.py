"""背包/装备界面 (原版窗口样式) + 头像/光标 回归."""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest

from core.save_manager import new_game_save
from core import party as party_mod


@pytest.fixture(scope="module")
def _pygame():
    pygame.init()
    pygame.display.set_mode((640, 480))
    yield


def _inv(items=((128, 1), (305, 1))):
    from scenes.inventory import InventoryScene
    save = new_game_save()
    for iid, n in items:
        save.inventory.add(iid, n)
    sc = InventoryScene(pygame.Surface((640, 480)), None, None, save)
    return sc, save


def _key(sc, k):
    sc.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k))


def test_draw_and_cursor_assets(_pygame):
    from core import ui_cursor, portraits
    sc, _ = _inv()
    sc.draw()                                   # 不应崩
    assert ui_cursor.arrow("right") is not None             # WHARROW 光标
    assert portraits.head_face("孙悟空", 32) is not None     # 角色头像
    assert portraits.head_face("ps_CMAN000", 32) is not None  # 资源名也可


def test_use_consumable_restores_and_consumes(_pygame):
    sc, save = _inv(((299, 2),))                # 恢复药
    from core.items import item_effect
    hp, _mp = item_effect(299)
    assert hp
    slot = party_mod.NAME_TO_SLOT["美娜"]
    ch = save.characters[slot]
    ch.CurrentHP = max(1, ch.MaxHP - hp - 5)
    before = ch.CurrentHP
    cnt0 = save.inventory.count(299)
    sc.sel = next(i for i, (iid, _) in enumerate(sc.items) if iid == 299)
    _key(sc, pygame.K_RETURN)
    assert ch.CurrentHP > before
    assert save.inventory.count(299) == cnt0 - 1


def test_equip_weapon_into_hand(_pygame):
    sc, save = _inv(((128, 1),))                # 如意双截棍 (武器)
    from core.items import get_item_category, ItemCategory
    assert get_item_category(128) is ItemCategory.WEAPON
    sc.sel = next(i for i, (iid, _) in enumerate(sc.items) if iid == 128)
    _key(sc, pygame.K_RETURN)                   # → 装备模式
    assert sc.mode == "equip"
    _key(sc, pygame.K_RETURN)                   # 给当前队员装备
    assert sc.mode == "list"
    slot = party_mod.NAME_TO_SLOT["美娜"]
    assert save.characters[slot].Hand == 128
    assert save.inventory.count(128) == 0


def test_esc_returns_to_parent(_pygame):
    sc, _ = _inv()
    _key(sc, pygame.K_ESCAPE)
    assert sc.next_scene is None                # parent=None
