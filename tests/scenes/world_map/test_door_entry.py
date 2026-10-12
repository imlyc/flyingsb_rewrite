"""房屋门进出落点: 从屋里出来应站在**该屋门口**, 而不是城镇默认出生点 (村口大门)."""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest

from core.audio_manager import AudioManager
from core.save_manager import new_game_save
from core import world_graph
from scenes.world_map.scene import WorldMapScene

TOWN = "TFI0___P"
# 五指村: (房门格, 屋内子图 id)
DOORS = [(8, 13, 23), (15, 10, 24), (26, 14, 25), (34, 9, 26),
         (7, 30, 27), (22, 36, 28), (29, 36, 29)]


@pytest.fixture(scope="module")
def _pygame():
    pygame.init()
    pygame.display.set_mode((800, 600))
    yield


def _scene():
    sc = WorldMapScene(pygame.Surface((800, 600)), AudioManager(), save=new_game_save())
    sc.on_enter()
    sc.next_scene = None
    sc.enter_location(TOWN, auto_beat=False)
    sc.next_scene = None
    return sc


def test_exit_house_lands_at_that_house_door(_pygame):
    """逐个房门验证: 进屋 → 出门, 落点必须是该门 (或其门前), 不能是 (13,39) 村口."""
    sc = _scene()
    town_spawn = world_graph.spawn(TOWN)
    assert town_spawn == (13, 39)                      # 默认落点 = 村口大门 (曾经的 bug 现象)
    for (dx, dy, _hid) in DOORS:
        sc.enter_location(TOWN, auto_beat=False)
        sc.next_scene = None
        assert sc.passable_at(dx, dy), f"房门({dx},{dy}) 走不进去"
        sc.player_x, sc.player_y = dx, dy
        sc.subpx = sc.subpy = 0.0
        sc._check_transition()                         # 进门
        assert sc.location_base != TOWN
        ix, iy = sc.player_x, sc.player_y              # 屋内的落点
        sc.player_x, sc.player_y = ix, iy - 1          # 往屋里走一格
        sc._check_transition()
        door = next(iter(sc._transitions))             # 屋内那道回村的门
        sc.player_x, sc.player_y = door
        sc.subpx = sc.subpy = 0.0
        sc._check_transition()                         # 出门
        assert sc.location_base == TOWN
        assert (sc.player_x, sc.player_y) in {(dx, dy), (dx, dy + 1)}, \
            f"从 ({dx},{dy}) 的房子出来, 却落在 {(sc.player_x, sc.player_y)} (非该屋门口)"


def test_entry_spawn_lands_on_reverse_door(_pygame):
    """落点 = 反向门那格 (门/门槛 flag=3 可走 -> 直接落脚门垫); 无反向门 -> None."""
    from core import real_map as realm
    sc = _scene()
    sp = sc._entry_spawn("TFI0___P", 23)
    assert sp == (8, 13)                                        # 屋 23 在村里的门
    assert realm.load("TFI0___P").passable(*sp)                 # 且真的站得住
    sp2 = sc._entry_spawn("TFI0_00P", 22)                       # 屋内: 门垫或门内那格
    assert sp2 in {(9, 15), (9, 14)}, sp2
    assert realm.load("TFI0_00P").passable(*sp2)
    assert sc._entry_spawn("TFI0___P", 476) is None             # 小森林 -> 村口无反向门
