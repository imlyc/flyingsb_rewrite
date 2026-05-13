"""terrain.py: 占位测试地图 / Tile 通行性."""

from scenes.world_map.terrain import (
    MAP_H,
    MAP_W,
    TILES,
    TerrainType,
    build_test_map,
)


def test_map_dimensions_30x30():
    grid = build_test_map()
    assert MAP_W == 30 and MAP_H == 30
    assert len(grid) == 30
    assert all(len(row) == 30 for row in grid)


def test_border_is_water():
    """边缘一圈水."""
    grid = build_test_map()
    for x in range(MAP_W):
        assert grid[0][x] == TerrainType.WATER
        assert grid[MAP_H - 1][x] == TerrainType.WATER
    for y in range(MAP_H):
        assert grid[y][0] == TerrainType.WATER
        assert grid[y][MAP_W - 1] == TerrainType.WATER


def test_mountain_ridge_with_gaps():
    """中部山脉带 y=14/15, x=3..MAP_W-3, 但 x∈{10,11,18,19} 是通行缺口."""
    grid = build_test_map()
    for x in range(3, MAP_W - 3):
        if x in (10, 11, 18, 19):
            assert grid[14][x] != TerrainType.MOUNTAIN
            assert grid[15][x] != TerrainType.MOUNTAIN
        else:
            assert grid[14][x] == TerrainType.MOUNTAIN
            assert grid[15][x] == TerrainType.MOUNTAIN


def test_dungeons_at_expected_positions():
    """两个地牢: (15, 8) 普通敌组, (5, 18) 乌鸦组. battle_launch 据此分敌人."""
    grid = build_test_map()
    assert grid[8][15] == TerrainType.DUNGEON
    assert grid[18][5] == TerrainType.DUNGEON


def test_towns_at_expected_positions():
    grid = build_test_map()
    for x, y in [(5, 5), (24, 6), (8, 22), (22, 24)]:
        assert grid[y][x] == TerrainType.TOWN


def test_tile_passability():
    """通行性: 草/城/地牢 可走, 水/山不可."""
    assert TILES[TerrainType.GRASS].passable
    assert TILES[TerrainType.TOWN].passable
    assert TILES[TerrainType.DUNGEON].passable
    assert not TILES[TerrainType.WATER].passable
    assert not TILES[TerrainType.MOUNTAIN].passable


def test_player_start_position_is_passable():
    """玩家起点 (3, 3) 必须是 grass / 通行的 (WorldMapScene.__init__ 写死了 3,3)."""
    grid = build_test_map()
    assert TILES[grid[3][3]].passable
