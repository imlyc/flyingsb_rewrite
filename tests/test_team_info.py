"""隊伍情報 / 裝備 (scenes/team_info.py + core/equipment.py) 回归: 换装属性重算 (exe FUN_00433296)、背包增减、
候选列表规则 (FUN_00424162)、竞技场装备记忆."""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

from core import equipment as EQ
from core.character import CHARACTER_NAMES, UNSET
from core.inventory import Inventory
from core.items import item_table_entry

pytestmark = pytest.mark.skipif(item_table_entry(31) is None or "cls" not in (item_table_entry(31) or {}),
                                reason="需要 assets/items_table.json (tools.extract_item_table 新版)")


@pytest.fixture(scope="module")
def _pygame():
    pygame.init()
    pygame.display.set_mode((800, 600))
    yield


def _goku():
    """存档 1 孙悟空 Lv38 的装备/裸值 (Save1.dat 实测: 力 75 智 45 敏 100 攻 1604 防 700 运 60)."""
    from core import character_data
    ch = character_data.make_character("孙悟空")
    ch.Unknow_2, ch.Unknow_3, ch.Unknow_4, ch.Unknow_5, ch.Unknow_6, ch.Unknow_7 = 75, 35, 70, 604, 161, 50
    ch.Head, ch.Body, ch.Hand, ch.Accessories1, ch.Accessories2 = 31, 91, 128, 327, 296
    return ch


def test_recompute_matches_save1():
    ch = _goku()
    EQ.recompute_stats(ch)
    assert (ch.Power, ch.Wisdom, ch.Agile, ch.Attack, ch.Defence, ch.Luck) == (75, 45, 100, 1604, 700, 60)


def test_preview_and_equip_moves_inventory():
    ch = _goku()
    EQ.recompute_stats(ch)
    inv = Inventory({33: 2})
    # 头盔 31 (防 92) → 33 (防 141): 预览 防御 700 → 749
    assert EQ.preview_stats(ch, 0, 33)[4] == 700 - 92 + 141
    assert EQ.preview_stats(ch, 0, None)[4] == 700 - 92            # 解除
    EQ.equip(ch, 0, 33, inv)
    assert ch.Head == 33 and ch.Defence == 749
    assert inv.count(33) == 1 and inv.count(31) == 1              # 新的 -1, 旧的回背包
    EQ.equip(ch, 0, None, inv)                                    # 解除
    assert ch.Head == UNSET and inv.count(33) == 2 and ch.Defence == 700 - 92


def test_candidates_rules():
    ch = _goku()
    inv = Inventory({22: 1, 33: 1, 0: 1, 64: 1, 124: 1, 199: 1, 272: 1, 273: 1, 201: 1})
    head = EQ.candidates(ch, 1, 0, inv)
    assert head[0][0] == EQ.UNEQUIP
    ids = [i for i, _ in head[1:]]
    assert ids == [22, 33]          # 0 普通帽子 (位 0x1fff) / 64 女神頭飾 (紫河) 悟空 (位 0x4000) 不能戴
    # 头盔 31 带 kind&1 (緊箍): 头部锁死, 全部灰 (含 解除, 与原版截图一致)
    assert not any(en for _, en in head)
    hand = EQ.candidates(ch, 1, 2, inv)
    assert all(i != EQ.UNEQUIP for i, _ in hand)                   # 手部没有 解除裝備
    assert [i for i, _ in hand] == [124]                           # 如意棒 199 不是悟空的
    # 饰品: 已带 五彩窗簾 (盾类 kind 0x80) → 另一槽的盾灰显
    acc = dict(EQ.candidates(ch, 1, 3, inv))
    assert acc[272] is False and acc[273] is False and acc[201] is True   # 護肩帶 (kind 0x80) 与 五彩窗簾 冲突


def _members(ch):
    from scenes.team_info import Member
    return [Member("孙悟空", ch, 1)]


def _run(sc, keys, ticks=30):
    for k in keys:
        sc._keys.append(k)
        for _ in range(ticks):
            sc.step()


def test_scene_equip_flow(_pygame):
    from scenes import team_info as TI
    ch = _goku()
    ch.Head = UNSET                                     # 空头部 → 可换
    EQ.recompute_stats(ch)
    inv = Inventory({22: 3, 33: 1})
    changed = []
    sc = TI.TeamInfoScene(pygame.Surface((800, 600)), None, _members(ch), inv, 1234, "RET",
                          on_change=changed.append)
    TI.TeamInfoScene._sub_row = 0
    sc.sub_row = 0
    sc.list_mem[:] = [0, 0, 0, 0]
    for _ in range(40):
        sc.step()
    assert sc.focus is sc.wins[TI.W_SUB]
    _run(sc, [TI.K_DOWN, TI.K_DOWN, TI.K_OK])           # 子菜单 → 裝備
    assert sc.focus is sc.wins[TI.W_EQUIP]
    _run(sc, [TI.K_OK])                                 # 头部 → 列表 (解除 / 22 / 33)
    lst = sc.wins[TI.W_LIST]
    assert [i for i, _ in lst.entries] == [EQ.UNEQUIP, 22, 33]
    _run(sc, [TI.K_DOWN, TI.K_DOWN, TI.K_OK])           # 选 33
    assert TI.W_LIST not in sc.wins and sc.focus is sc.wins[TI.W_EQUIP]
    assert ch.Head == 33 and inv.count(33) == 0 and inv.count(22) == 3
    assert ch.Defence == 700 - 92 + 141 and changed
    sc.draw()
    _run(sc, [TI.K_CANCEL, TI.K_CANCEL], ticks=40)      # 装备栏 → 子菜单 → 关闭
    assert sc.next_scene == "RET"


def test_scene_rotate_and_draw(_pygame):
    from core import character_data
    from scenes import team_info as TI
    ms = [TI.Member(n, character_data.make_character(n), s)
          for s, n in CHARACTER_NAMES.items() if s in (1, 3, 12)]
    sc = TI.TeamInfoScene(pygame.Surface((800, 600)), None, ms, Inventory(), 0, None)
    for _ in range(40):
        sc.step()
    _run(sc, [TI.K_LEFT], ticks=25)
    assert sc.cur == 1 and sc.focus is sc.wins[TI.W_SUB]
    sc.draw()


def test_arena_equipment_memory(tmp_path, monkeypatch):
    from scenes.arena import store
    from scenes.arena.roster import build_player_character, build_player_unit
    monkeypatch.setattr(store, "_PATH", tmp_path / "arena.json")
    store.save_selection(["孙悟空"], [], {"孙悟空": 40})
    store.save_equipment("孙悟空", [None, 65, 128, UNSET, -1])
    assert store.load_equipment() == {"孙悟空": [-1, 65, 128, -1, -1]}
    store.save_selection(["孙悟空"], [], {"孙悟空": 41})          # 写名单不丢装备
    assert store.load_equipment()["孙悟空"][2] == 128
    ch = build_player_character("孙悟空", 40, store.load_equipment()["孙悟空"])
    assert ch.Hand == 128 and ch.Head == UNSET
    assert ch.Attack == ch.Unknow_5 + 960                          # 如意雙截棍 攻 960 (FUN_00433296)
    bare = build_player_unit("孙悟空", level=40)
    u = build_player_unit("孙悟空", level=40, equipment=store.load_equipment()["孙悟空"])
    assert u.attack == bare.attack + 960


def test_world_map_e_opens_team_info(_pygame):
    from core.audio_manager import AudioManager
    from core.save_manager import new_game_save
    from scenes.team_info import TeamInfoScene
    from scenes.world_map.scene import WorldMapScene
    world = WorldMapScene(pygame.Surface((800, 600)), AudioManager(), save=new_game_save())
    world.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_e))
    sc = world.next_scene
    assert isinstance(sc, TeamInfoScene) and sc.members and sc.inv is world.save.inventory
    for _ in range(40):
        sc.step()
    sc.draw()
