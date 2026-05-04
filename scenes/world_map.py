"""世界地图场景: 30x30 占位 tile, WASD/方向键移动, 镜头跟随玩家."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pygame

from core.audio_manager import AudioManager
from core.save_manager import SaveData
from scenes.base import Scene
from scenes.menu import load_chinese_font

TILE_SIZE = 32
MAP_W = 30
MAP_H = 30
MOVE_COOLDOWN_MS = 120  # 移动节流, 避免按住一下飞


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


def _build_test_map() -> list[list[TerrainType]]:
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


class WorldMapScene(Scene):
    """玩家在 30x30 网格上走动. ESC 返回主菜单."""

    HUD_BG = (0, 0, 0, 180)
    HUD_TEXT = (255, 255, 255)
    PLAYER_COLOR = (255, 50, 200)

    def __init__(
        self,
        surface: pygame.Surface,
        audio: AudioManager,
        save: SaveData | None = None,
    ) -> None:
        super().__init__(surface)
        self.audio = audio
        self.save = save
        self.grid = _build_test_map()
        self.player_x = 3   # 起点 (tile coords)
        self.player_y = 3
        self.last_move_at = 0
        self.font = load_chinese_font(20)

    # ------- 生命周期 -------
    def on_enter(self) -> None:
        try:
            self.audio.play_bgm("world1.wav")
        except FileNotFoundError as e:
            print(f"world BGM 缺失: {e}")

    # ------- 输入 -------
    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            from scenes.menu import TitleScene
            self.next_scene = TitleScene(self.surface, self.audio)
            return True
        return True

    # ------- 更新 -------
    def update(self, dt_ms: int) -> None:
        keys = pygame.key.get_pressed()
        dx = (keys[pygame.K_RIGHT] or keys[pygame.K_d]) - (keys[pygame.K_LEFT] or keys[pygame.K_a])
        dy = (keys[pygame.K_DOWN]  or keys[pygame.K_s]) - (keys[pygame.K_UP]   or keys[pygame.K_w])
        if dx == 0 and dy == 0:
            return
        # 节流, 防止按一下走多格
        now = pygame.time.get_ticks()
        if now - self.last_move_at < MOVE_COOLDOWN_MS:
            return
        # 优先水平方向, 避免对角线斜跳
        if dx != 0:
            dy = 0
        nx, ny = self.player_x + dx, self.player_y + dy
        if 0 <= nx < MAP_W and 0 <= ny < MAP_H and TILES[self.grid[ny][nx]].passable:
            self.player_x, self.player_y = nx, ny
            self.last_move_at = now

    # ------- 渲染 -------
    def _camera_offset(self) -> tuple[int, int]:
        """让玩家居中, 边缘时夹紧."""
        sw, sh = self.surface.get_size()
        cx = self.player_x * TILE_SIZE + TILE_SIZE // 2 - sw // 2
        cy = self.player_y * TILE_SIZE + TILE_SIZE // 2 - sh // 2
        max_cx = MAP_W * TILE_SIZE - sw
        max_cy = MAP_H * TILE_SIZE - sh
        cx = max(0, min(cx, max(0, max_cx)))
        cy = max(0, min(cy, max(0, max_cy)))
        return cx, cy

    def draw(self) -> None:
        self.surface.fill((0, 0, 0))
        cx, cy = self._camera_offset()
        sw, sh = self.surface.get_size()

        # 只画可见范围内的 tile
        x_start = max(0, cx // TILE_SIZE)
        y_start = max(0, cy // TILE_SIZE)
        x_end = min(MAP_W, (cx + sw) // TILE_SIZE + 1)
        y_end = min(MAP_H, (cy + sh) // TILE_SIZE + 1)
        for y in range(y_start, y_end):
            for x in range(x_start, x_end):
                tile = TILES[self.grid[y][x]]
                rect = pygame.Rect(
                    x * TILE_SIZE - cx, y * TILE_SIZE - cy, TILE_SIZE, TILE_SIZE
                )
                pygame.draw.rect(self.surface, tile.color, rect)
                # 城镇/地牢加边框区分
                if tile.terrain in (TerrainType.TOWN, TerrainType.DUNGEON):
                    pygame.draw.rect(self.surface, (0, 0, 0), rect, 2)

        # 玩家
        prect = pygame.Rect(
            self.player_x * TILE_SIZE - cx + 4,
            self.player_y * TILE_SIZE - cy + 4,
            TILE_SIZE - 8, TILE_SIZE - 8,
        )
        pygame.draw.rect(self.surface, self.PLAYER_COLOR, prect)

        self._draw_hud()

    def _draw_hud(self) -> None:
        # 半透明黑底
        hud = pygame.Surface((self.surface.get_width(), 36), pygame.SRCALPHA)
        hud.fill(self.HUD_BG)
        self.surface.blit(hud, (0, 0))
        loc = self.save.location if self.save else "未读取存档"
        money = self.save.money if self.save else 0
        text = self.font.render(
            f"地点: {loc}    金钱: {money}    位置: ({self.player_x},{self.player_y})    [ESC] 返回菜单",
            True, self.HUD_TEXT,
        )
        self.surface.blit(text, (10, 8))
