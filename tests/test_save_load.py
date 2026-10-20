"""存档/读档 (ESC 暂停菜单) 回归."""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest

from core import game_save
from core.save_manager import new_game_save


@pytest.fixture(scope="module")
def _pygame():
    pygame.init()
    pygame.display.set_mode((640, 480))
    yield


@pytest.fixture()
def tmp_saves(tmp_path, monkeypatch):
    monkeypatch.setattr(game_save, "SAVE_DIR", tmp_path)
    return tmp_path


def _world(items=((128, 1),)):
    from core.audio_manager import AudioManager
    from scenes.world_map.scene import WorldMapScene
    save = new_game_save()
    for iid, n in items:
        save.inventory.add(iid, n)
    sc = WorldMapScene(pygame.Surface((640, 480)), AudioManager(), save=save)
    sc.on_enter()
    sc.next_scene = None
    return sc


def test_round_trip_restores_progress(_pygame, tmp_saves):
    sc = _world()
    sc.enter_location("TFI0___P", auto_beat=False)
    sc.next_scene = None
    sc.save.money = 4321
    sc.story.state.flags.update({"PROLOGUE", "ARRIVED"})
    sc.story.state.done.update({"intro", "c1_forest"})
    sc.player_x, sc.player_y = 20, 21

    assert game_save.slot_summary(0) is None                # 空槽
    game_save.save_game(sc.save, sc.story.state, sc.location_base,
                        sc.player_x, sc.player_y, 0)

    info = game_save.slot_summary(0)
    assert info and info["money"] == 4321

    data = game_save.load_game(0)
    assert data is not None
    assert (data.base, data.x, data.y) == ("TFI0___P", 20, 21)
    assert data.save.money == 4321
    assert {"intro", "c1_forest"} <= data.done
    assert {"PROLOGUE", "ARRIVED"} <= data.flags
    assert data.save.inventory.count(128) == 1


def test_loaded_world_scene_rebuilds(_pygame, tmp_saves):
    sc = _world()
    sc.enter_location("TFI0___P", auto_beat=False)
    sc.next_scene = None
    sc.player_x, sc.player_y = 20, 21
    sc.story.state.flags.add("PROLOGUE")
    sc.story.state.done.add("intro")
    game_save.save_game(sc.save, sc.story.state, sc.location_base, 20, 21, 1)

    data = game_save.load_game(1)
    from scenes.pause import PauseScene
    from core.audio_manager import AudioManager
    pause = PauseScene(pygame.Surface((640, 480)), None, AudioManager(), mode="load")
    new_scene = pause._build_world(data)
    assert new_scene.location_base == "TFI0___P"
    assert (new_scene.player_x, new_scene.player_y) == (20, 21)
    assert "intro" in new_scene.story.state.done
    assert "PROLOGUE" in new_scene.story.state.flags


def test_pause_menu_save_and_escape(_pygame, tmp_saves):
    sc = _world()
    sc.enter_location("TBB0___P", auto_beat=False)
    sc.next_scene = None
    from scenes.pause import PauseScene
    pause = PauseScene(pygame.Surface((640, 480)), sc, sc.audio)
    pause.draw()
    # 选中"保存存档" → Enter 进槽位界面
    pause.cursor = pause._items().index("保存存档")
    pause.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    assert pause.mode == "save"
    pause.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    assert game_save.slot_summary(0) is not None            # 已写入
    # ESC 从槽位界面退回菜单, 再 ESC 继续游戏
    pause.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    assert pause.mode == "menu"
    pause.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    assert pause.next_scene is sc


def test_pause_menu_has_inventory(_pygame, tmp_saves):
    """ESC 菜单里的「背包物品」能开背包; 且 InventoryScene 必须有 on_enter
    (主循环 switch_scene 会调, 缺了按 I 直接 AttributeError 崩)."""
    from scenes.inventory import InventoryScene
    assert hasattr(InventoryScene, "on_enter") and hasattr(InventoryScene, "on_exit")

    sc = _world()
    sc.enter_location("TBB0___P", auto_beat=False)
    sc.next_scene = None
    from scenes.pause import PauseScene
    pause = PauseScene(pygame.Surface((640, 480)), sc, sc.audio)
    assert "背包物品" in pause._items()
    pause.cursor = pause._items().index("背包物品")
    pause.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    inv = pause.next_scene
    assert isinstance(inv, InventoryScene)
    inv.on_enter()                     # 不抛异常
    inv.draw()


def test_slot_summary_shows_party_levels(_pygame, tmp_saves):
    """存档槽要显示队伍 (名字 + 等级)."""
    from core import party as party_mod
    sc = _world()
    sc.enter_location("TFI0___P", auto_beat=False)
    sc.next_scene = None
    party_mod.activate_character(sc.save, "孙悟空")
    sc.story.state.party.append("孙悟空")
    sc.save.characters[party_mod.NAME_TO_SLOT["孙悟空"]].Level = 5
    game_save.save_game(sc.save, sc.story.state, sc.location_base, 1, 1, 0)

    info = game_save.slot_summary(0)
    levels = dict(info["party_info"])
    assert levels.get("孙悟空") == 5
    assert "美娜" in levels
    assert info["place"]                        # 中文地名
