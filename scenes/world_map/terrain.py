"""世界地图地形数据: TerrainType / Tile / TILES dict / 占位测试地图.

测试期用 _build_test_map() 拼一张 30x30 网格 (边水+中部山脉+城镇/地牢散布).
等 mapset.dll 反向出来后, 这层会被真实地图数据替换.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


MAP_W = 30
MAP_H = 30


class TerrainType(Enum):
    GRASS = "grass"
    WATER = "water"
    MOUNTAIN = "mountain"
    TOWN = "town"
    DUNGEON = "dungeon"


@dataclass(frozen=True)
class Tile:
    terrain: TerrainType
    color: tuple[int, int, int]
    passable: bool


TILES: dict[TerrainType, Tile] = {
    TerrainType.GRASS:    Tile(TerrainType.GRASS,    (76, 160, 80),   True),
    TerrainType.WATER:    Tile(TerrainType.WATER,    (50, 100, 200),  False),
    TerrainType.MOUNTAIN: Tile(TerrainType.MOUNTAIN, (130, 130, 130), False),
    TerrainType.TOWN:     Tile(TerrainType.TOWN,     (220, 200, 80),  True),
    TerrainType.DUNGEON:  Tile(TerrainType.DUNGEON,  (180, 60, 60),   True),
}


def build_test_map() -> list[list[TerrainType]]:
    """30x30 测试地图: 边缘水, 中部山脉带, 散布城镇/地牢."""
    G, W, M, T, D = (
        TerrainType.GRASS, TerrainType.WATER, TerrainType.MOUNTAIN,
        TerrainType.TOWN, TerrainType.DUNGEON,
    )
    grid = [[G for _ in range(MAP_W)] for _ in range(MAP_H)]

    # 边缘一圈水
    for x in range(MAP_W):
        grid[0][x] = grid[MAP_H - 1][x] = W
    for y in range(MAP_H):
        grid[y][0] = grid[y][MAP_W - 1] = W

    # 中部一条山脉带 (留缺口)
    for x in range(3, MAP_W - 3):
        if x in (10, 11, 18, 19):
            continue  # 通行缺口
        grid[14][x] = M
        grid[15][x] = M

    # 几个城镇
    for (x, y) in [(5, 5), (24, 6), (8, 22), (22, 24)]:
        grid[y][x] = T

    # 两个地牢
    for (x, y) in [(15, 8), (5, 18)]:
        grid[y][x] = D

    return grid
