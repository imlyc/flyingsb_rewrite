"""世界地图 (M 键): 原版地点表 + 去过/新解锁标记."""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest

from scenes.world_map import atlas as atlas_mod
from scenes.world_map.atlas import WorldAtlasScene, load_locations, load_markers


@pytest.fixture(scope="module")
def _pygame():
    pygame.init()
    pygame.display.set_mode((640, 480))
    yield


def _make(world, save):
    return WorldAtlasScene(pygame.Surface((640, 480)), world)


def _world_with(save):
    """最小 world 桩: story.state.flags + enter_location + save."""
    class _Story:
        state = type("S", (), {"flags": set()})()
    class _World:
        story = _Story()
        entered = None
        def enter_location(self, base, spawn=None):
            self.entered = base
            return True
    w = _World()
    w.save = save
    return w


# ---- 原版数据完整性 (tools/extract_worldmap.py 提取自 exe 0x14b41c) ----

def test_table_has_44_entries():
    locs = load_locations()
    assert len(locs) == 44


def test_anchor_entries_match_exe():
    by = {l["name_s"]: l for l in load_locations()}
    wz = by["五指村"]
    assert (wz["x"], wz["y"], wz["id"], wz["base"]) == (969, 1445, 22, "TFI0___P")
    assert by["阿尔夏"]["id"] == 348 and by["阿尔夏"]["base"] == "TAL0___P"
    # 关键纠错: 乌来城 = TOR0___P (旧手标表曾误指 TMO —— TMO 实为魔塔)
    assert by["乌来城"]["base"] == "TOR0___P"
    assert by["魔塔"]["base"] == "TMO0___P"
    assert by["欧明汉"]["base"] == "TOM0___P"


def test_marker_sprites_loaded(_pygame):
    m = load_markers()
    assert m is not None
    assert set(m) >= {"arrow0", "visited", "new", "locked"}
    assert m["visited"].get_size() == (8, 8)
    assert m["new"].get_size() == (9, 9)


# ---- 状态与解锁 ----

def test_initial_unlock_and_locking(_pygame):
    from core.save_manager import new_game_save
    save = new_game_save()
    save.world_visited = [22, 10]          # 去过五指村/雅士兰
    sc = _make(_world_with(save), save)
    states = {l["id"]: sc._state(l) for l in sc._locs}
    assert states[22] == "visited" and states[10] == "visited"
    assert states[30] == "locked"          # 五行山需 LEFT_VILLAGE
    assert states[348] == "locked"         # 阿尔夏需 WUKONG_JOINED
    # 蓝点地点不可选
    sel_ids = {sc._locs[i]["id"] for i in sc._vis}
    assert 30 not in sel_ids and 348 not in sel_ids


def test_flags_unlock_new_locations(_pygame):
    from core.save_manager import new_game_save
    save = new_game_save()
    save.world_visited = [22, 10]
    w = _world_with(save)
    sc = _make(w, save)
    w.story.state.flags.add("LEFT_VILLAGE")
    sc._refresh_vis()
    assert {sc._locs[i]["id"] for i in sc._vis} >= {30, 46}
    w.story.state.flags.add("WUKONG_JOINED")
    sc._refresh_vis()
    assert len(sc._vis) == 44              # 全部地点可选 (均解析出 base)


def test_enter_location_marks_visited(_pygame):
    """世界地图场景里 enter_location 后, 位置 ID 记入 save.world_visited."""
    from core.audio_manager import AudioManager
    from core.save_manager import new_game_save
    from scenes.world_map.scene import WorldMapScene
    save = new_game_save()
    sc = WorldMapScene(pygame.Surface((640, 480)), AudioManager(), save=save)
    sc.on_enter()
    assert sc.enter_location("TFI0___P")
    assert 22 in save.world_visited
    assert sc.enter_location("TAS0___P")
    assert 10 in save.world_visited
    # 同一地点不重复记录
    n = len(save.world_visited)
    sc.enter_location("TAS0___P")
    assert len(save.world_visited) == n


def test_draw_and_navigation(_pygame):
    from core.save_manager import new_game_save
    save = new_game_save()
    save.world_visited = [22, 10]
    sc = _make(_world_with(save), save)
    pygame.event.clear()
    sc.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN))
    assert sc.cursor == 1
    sc.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP))
    assert sc.cursor == 0
    sc.draw()                              # 不抛异常 (含小地图/标记/信息条)
    # ESC 返回世界
    sc.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    assert sc.next_scene is not None
