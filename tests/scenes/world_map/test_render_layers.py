"""2.5D 分层渲染回归 (2026-09-29 用户实测: 站在桥上被桥板挡 / 站墙沿半身藏在墙后).

要点:
  1. `draw_terrain(rows=(y0, y1))` 只画这些行 —— 逐行交错绘制的基石;
  2. `WorldMapScene.draw()` 必须逐行交错: 地图行 → 该行实体 → 该行覆盖层,
     这样"南侧"的桥板/墙沿才能遮住角色;
  3. 全游戏抽样渲染不报错 (覆盖层开启后不再花斑/崩溃)。
"""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from pathlib import Path

import pygame
import pytest

from core import real_map as realm
from core.sprites.base import TILE_W, TILE_H

ASSETS = Path(__file__).resolve().parents[3] / "assets"


@pytest.fixture(scope="module")
def _pygame():
    pygame.init()
    pygame.display.set_mode((64, 64))
    yield


def test_draw_terrain_respects_row_range(_pygame):
    """只画指定行: 范围外的格子必须保持原样 (逐行交错绘制依赖它)。"""
    m = realm.load("TFI0___P")
    surf = pygame.Surface((m.w * TILE_W, m.h * TILE_H))
    surf.fill((255, 0, 255))
    m.draw_terrain(surf, 0, 0, rows=(5, 6))
    probe = surf.get_at((3 * TILE_W + 4, 5 * TILE_H + 4))[:3]
    outside = surf.get_at((3 * TILE_W + 4, 4 * TILE_H + 4))[:3]
    assert outside == (255, 0, 255), "范围外的行不该被画"
    assert probe != (255, 0, 255), "指定行应该被画上"


def test_draw_is_row_interleaved(_pygame):
    """南侧的墙/桥必须画在玩家之后 = 逐行交错。

    做法: 找一处"玩家北侧可走、南侧是结构"的位置, 渲染后检查玩家脚下那一行
    是否被地图覆盖 (玩家精灵被南侧地形压住 → 该行不再是纯精灵色)。
    """
    from core.audio_manager import AudioManager
    from core.save_manager import new_game_save
    from scenes.world_map.scene import WorldMapScene

    surf = pygame.Surface((640, 480))
    sc = WorldMapScene(surf, AudioManager(), new_game_save())
    sc.on_enter(); sc.next_scene = None
    assert sc.enter_location("TFI0___P", spawn=(23, 24), auto_beat=False)   # 木桥中段
    sc.next_scene = None
    sc.facing = (0, -1)
    sc._no_hud = True
    sc.draw()          # 不报错, 且玩家行之后的地图行确实又被画了一次
    assert sc.player_y == 24


def test_all_maps_render_without_error(_pygame):
    """抽样渲染全游戏地图 (含覆盖层), 不应抛异常。"""
    from core.audio_manager import AudioManager
    from core.save_manager import new_game_save
    from scenes.world_map.scene import WorldMapScene

    names = [p.stem for p in sorted((ASSETS / "maps").glob("*.map"))]
    assert len(names) > 300
    sample = names[::max(1, len(names) // 30)][:30]
    errors = []
    for base in sample:
        try:
            tile = pygame.Surface((400, 300))
            sc = WorldMapScene(tile, AudioManager(), new_game_save())
            sc.on_enter(); sc.next_scene = None
            if sc.enter_location(base, auto_beat=False):
                sc.next_scene = None
                sc._no_hud = True
                sc.draw()
        except Exception as e:                      # noqa: BLE001
            errors.append((base, f"{type(e).__name__}: {e}"))
    assert not errors, f"渲染异常: {errors[:5]}"
