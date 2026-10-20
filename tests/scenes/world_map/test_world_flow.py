"""出村/小森林/选地点 行为回归 (修复: 起始小森林、出村开选地点、M 不弹序章)."""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest

from core.audio_manager import AudioManager
from core.save_manager import new_game_save
from core import world_graph
from scenes.world_map.scene import WorldMapScene
from scenes.world_map.atlas import WorldAtlasScene


@pytest.fixture(scope="module")
def _pygame():
    pygame.init()
    pygame.display.set_mode((800, 600))
    yield


def _scene():
    return WorldMapScene(pygame.Surface((800, 600)), AudioManager(), new_game_save())


def test_new_game_starts_in_xiaos森林(_pygame):
    sc = _scene()
    sc.on_enter()
    assert sc.enter_location("TBB0___P")            # 复刻 _action_new_game 的起点
    assert sc.location_base == "TBB0___P"
    assert 476 in sc.save.world_visited             # 小森林 id


def test_xiaos森林_south_exit_to_wuzhi(_pygame):
    """小森林南口必须**真的走得到** (空地南缘 y=12), 否则玩家会被困在起始村."""
    from collections import deque
    sc = _scene()
    sc.on_enter()
    sc.enter_location("TBB0___P")
    sc.next_scene = None
    sc.player_x, sc.player_y = 11, 12
    sc.subpx = sc.subpy = 0.0
    exits = [t for t in world_graph.transitions("TBB0___P").items() if t[1] == 22]
    assert exits, "小森林应接到五指村"
    # 从出生点 BFS, 确认至少一个出口格可达 (真实可玩性, 而不只是坐标存在)
    m = sc.real_map
    sp = m.start_pos()
    seen, q = {sp}, deque([sp])
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if (nx, ny) in seen or not (0 <= nx < m.w and 0 <= ny < m.h):
                continue
            if sc.passable_at(nx, ny):
                seen.add((nx, ny)); q.append((nx, ny))
    assert any(pos in seen for pos, _ in exits), "小森林出口不可达 (玩家会卡在起始村)"
    sc._check_transition()
    assert sc.location_base == "TFI0___P"           # 走到五指村


def test_wuzhi_south_exit_opens_atlas(_pygame):
    sc = _scene()
    sc.on_enter()
    sc.enter_location("TFI0___P")
    sc.player_x, sc.player_y = 13, 39              # 五指村南口 -> id0=T_LOC0_P(hub)
    sc.subpx = sc.subpy = 0.0
    sc._check_transition()
    assert isinstance(sc.next_scene, WorldAtlasScene)
    names = [sc.next_scene._locs[i]["name_s"] for i in sc.next_scene._vis]
    assert "小森林" in names                     # 起步村应可回选


def test_travel_enters_without_auto_beat_but_talk_triggers(_pygame):
    """选地点/步行抵达剧情地点只是进图 (不再自动弹地点剧情); 面对 NPC 按空格才触发该地剧情."""
    sc = _scene()
    sc.on_enter()
    sc.enter_location("TBB0___P")           # 起点小森林: 序章(无地点约束) 自动播
    for bid in ("intro", "c1_forest"):
        sc.story.state.mark_done(next(x for x in sc.story.state.beats if x.id == bid), sc.save)
    sc.next_scene = None
    atlas = WorldAtlasScene(sc.surface, sc, sc.audio)
    atlas.cursor = next(i for i, l in enumerate(atlas._locs) if l["id"] == 22)
    atlas._enter()
    assert sc.location_base == "TFI0___P"
    assert sc.next_scene is None            # 进图不自动弹剧情
    npc = next(n for n in sc.npc_layer._extra if n["_talk"])
    sc._talk_to(npc)                        # 面对 NPC 说话 → 触发第2章「抵达」
    assert type(sc.next_scene).__name__ in ("DialogueScene", "CutsceneScene")
