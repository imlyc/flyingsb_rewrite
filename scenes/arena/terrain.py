"""竞技场专用地图 + 地形渲染.

ArenaTerrain 同时充当 BattleScene 需要的 "world_map" (提供 draw_terrain / _camera_offset)
和战斗逻辑需要的 BattleMap (障碍集合). 一张平坦草地竞技场, 四周一圈装饰性石墙 (障碍).
"""

from __future__ import annotations

import pygame

from core.battle.data import BattleMap
from core.sprites.base import TILE_W, TILE_H

# 竞技场尺寸 (格). 比屏幕 (12.5×12.5 格) 略大, 留少量滚动.
ARENA_W = 16
ARENA_H = 13

# 地表两色棋盘 (草地竞技场), + 边墙色
GRASS_A = (88, 158, 86)
GRASS_B = (78, 146, 78)
WALL = (96, 92, 84)
WALL_EDGE = (60, 56, 50)


class ArenaTerrain:
    """轻量地形提供者. BattleScene 只调用 draw_terrain() 和 _camera_offset()."""

    def __init__(self, w: int = ARENA_W, h: int = ARENA_H) -> None:
        self.w = w
        self.h = h
        # 四周一圈墙做障碍, 内部全开放
        self.walls: set[tuple[int, int]] = set()
        for x in range(w):
            self.walls.add((x, 0))
            self.walls.add((x, h - 1))
        for y in range(h):
            self.walls.add((0, y))
            self.walls.add((w - 1, y))

    # ---- 给战斗逻辑用 ----
    def build_battle_map(self) -> BattleMap:
        bm = BattleMap(self.w, self.h)
        bm.obstacles |= self.walls
        return bm

    def passable(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h and (x, y) not in self.walls

    # ---- BattleScene 期望的 "world_map" 接口 ----
    def _camera_offset(self) -> tuple[int, int]:
        """初始镜头: 居中整张地图 (BattleScene 之后会按当前单位平滑跟随)."""
        return (max(0, (self.w * TILE_W) // 2 - 400),
                max(0, (self.h * TILE_H) // 2 - 300))

    def draw_terrain(self, surface: pygame.Surface, cam_x: int, cam_y: int) -> None:
        sw, sh = surface.get_size()
        x0 = max(0, cam_x // TILE_W)
        y0 = max(0, cam_y // TILE_H)
        x1 = min(self.w, (cam_x + sw) // TILE_W + 1)
        y1 = min(self.h, (cam_y + sh) // TILE_H + 1)
        for y in range(y0, y1):
            for x in range(x0, x1):
                rect = pygame.Rect(x * TILE_W - cam_x, y * TILE_H - cam_y, TILE_W, TILE_H)
                if (x, y) in self.walls:
                    pygame.draw.rect(surface, WALL, rect)
                    pygame.draw.rect(surface, WALL_EDGE, rect, 2)
                else:
                    color = GRASS_A if (x + y) % 2 == 0 else GRASS_B
                    pygame.draw.rect(surface, color, rect)
