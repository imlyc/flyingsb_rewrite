"""商店 (原版 SPAN04 界面) 回归: 购买 / 贩卖 / 换档."""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest

from core.save_manager import new_game_save
from core.prices import buy_price, sell_price


@pytest.fixture(scope="module")
def _pygame():
    pygame.init()
    pygame.display.set_mode((640, 480))
    yield


def _scene(base="TAS0_09P", money=100000):
    from scenes.shop import ShopScene
    save = new_game_save()
    save.money = money
    return ShopScene(pygame.Surface((640, 480)), None, base, save), save


def _key(sc, k):
    sc.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k))


def test_buy_deducts_money_and_adds_item(_pygame):
    sc, save = _scene()
    sc.draw()                                   # 不应崩
    iid = sc.buy_items[0]
    price = buy_price(iid)
    before = save.money
    _key(sc, pygame.K_RETURN)
    assert save.money == before - price
    assert save.inventory.count(iid) >= 1


def test_sell_adds_money_and_removes_item(_pygame):
    sc, save = _scene()
    save.inventory.add(299, 3)                   # 恢复药
    _key(sc, pygame.K_RIGHT)                     # → 販賣
    assert sc.tab == 1
    rows = sc._sell_list()
    assert any(i == 299 for i, _ in rows)
    sc.cursor = next(i for i, (iid, _) in enumerate(rows) if iid == 299)
    before = save.money
    cnt0 = save.inventory.count(299)
    _key(sc, pygame.K_RETURN)
    assert save.money == before + sell_price(299)
    assert save.inventory.count(299) == cnt0 - 1


def test_tab_cycling_and_leave(_pygame):
    sc, _ = _scene()
    _key(sc, pygame.K_RIGHT); assert sc.tab == 1     # 販賣
    _key(sc, pygame.K_RIGHT); assert sc.tab == 2     # 離開
    sc.return_scene = None
    _key(sc, pygame.K_LEFT)                          # 回到 販賣
    assert sc.tab == 1
    _key(sc, pygame.K_ESCAPE)
    assert sc.next_scene is None                     # ESC 退出


def test_item_icons_grid(_pygame):
    """SITEM 图标集: item_id 即格号 (20x20/32列)."""
    from core import item_icons
    for iid in (0, 2, 3, 128, 200, 299, 302, 305):
        s = item_icons.icon(iid)
        assert s is not None and s.get_size() == (20, 20), iid
    assert item_icons.icon(99999) is None


def test_party_portraits_use_real_sprites(_pygame):
    """右侧队伍头像用当前队伍真精灵 (而非面板烘焙的死头像); 缺精灵也不崩."""
    from core import party as party_mod
    sc, save = _scene()
    party_mod.activate_character(save, "孙悟空")
    sc.draw()                                   # 不应崩
    assert sc._face("孙悟空") is not None
    assert sc._face("美娜") is not None


def test_inn_restores_party(_pygame):
    sc, save = _scene("TAS0_01P")
    from core import party as party_mod
    ch = save.characters[party_mod.NAME_TO_SLOT["美娜"]]
    ch.CurrentHP = 1
    before = save.money
    _key(sc, pygame.K_RETURN)
    assert ch.CurrentHP == ch.MaxHP
    assert save.money < before
