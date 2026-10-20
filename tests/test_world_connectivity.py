"""步行连通性 + 剧情门控回归测试 (补上前3章纯步行缺口).

- T_LOC0_P(五指村/五行山世界) ↔ T_LOC1_P(雅士兰世界) 现已用跨簇传送相连, 纯步行可达雅士兰.
- 五行山步行入口 (T_LOC0_P 10,3) 受 LEFT_VILLAGE 门控, 与 M 键世界地图 unlock 一致.
"""

import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from core import real_map as realm
from core import world_graph
from core.save_manager import new_game_save
from core.story import Director
from scenes.world_map.scene import WorldMapScene


def test_cross_cluster_links_exist_and_passable():
    # T_LOC0_P 新增 (10,6) -> T_LOC1_P(id 1)
    tr = world_graph.transitions("T_LOC0_P")
    assert tr.get((10, 6)) == 1
    # T_LOC1_P 新增 (5,5) -> T_LOC0_P(id 0)
    tr1 = world_graph.transitions("T_LOC1_P")
    assert tr1.get((5, 5)) == 0
    # 两个传送落点必须确实可通行 (否则玩家走不上去)
    m0 = realm.load("T_LOC0_P")
    assert m0.passable(10, 6), "T_LOC0_P (10,6) 不可通行, 步行卡死"
    m1 = realm.load("T_LOC1_P")
    assert m1.passable(5, 5), "T_LOC1_P (5,5) 不可通行, 步行卡死"


def test_five_fingers_gate_declared():
    # 五行山步行入口需先离开五指村 (LEFT_VILLAGE)
    assert world_graph.gate_for("T_LOC0_P", 10, 3) == "LEFT_VILLAGE"
    # 跨簇链接不应被门控
    assert world_graph.gate_for("T_LOC0_P", 10, 6) is None
    assert world_graph.gate_for("T_LOC1_P", 5, 5) is None


def _make_scene():
    pygame.init()
    surf = pygame.Surface((640, 480))
    from core.audio_manager import AudioManager
    scene = WorldMapScene(surf, AudioManager(), save=new_game_save())
    scene.on_enter()
    return scene


def test_gate_blocks_without_flag():
    scene = _make_scene()
    assert scene.enter_location("T_LOC0_P")
    # 没做五指村线: 站五行山入口 (10,3) 试图步行进入 -> 被挡
    scene.story.state.flags.clear()
    scene.player_x, scene.player_y = 10, 3
    scene._check_transition()
    assert scene.location_base == "T_LOC0_P", "缺 flag 仍被传送到五行山"
    assert scene._story_toast and "无法前往" in scene._story_toast


def test_gate_allows_with_flag():
    scene = _make_scene()
    assert scene.enter_location("T_LOC0_P")
    scene.story.state.flags.add("LEFT_VILLAGE")
    scene.player_x, scene.player_y = 10, 3
    scene._check_transition()
    assert scene.location_base == "TOH0_00P", "有 flag 应进入五行山"


def test_cross_cluster_warp_on_foot():
    scene = _make_scene()
    assert scene.enter_location("T_LOC0_P")
    # 五指村世界走到 (10,6) -> 雅士兰世界 T_LOC1_P
    scene.story.state.flags.clear()
    scene.player_x, scene.player_y = 10, 6
    scene._check_transition()
    assert scene.location_base == "T_LOC1_P", "跨簇传送失败, 仍停留在五指村世界"


def test_story_chain_still_reaches_woohsing():
    # 校验门控修复未破坏前3章剧情链 (对照 test_chapters_1_3)
    d = Director(save=new_game_save())
    guard = 0
    while "SPRITES" not in d.state.flags:
        b = d.current()
        if b is None:
            break
        d.apply_presave(b, None)
        d.apply_postbattle(b, None)
        guard += 1
        assert guard < 50
    assert "SPRITES" in d.state.flags
