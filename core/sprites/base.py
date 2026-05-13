"""低阶 sprite 基础设施: 路径常量 / 朝向枚举 / SpriteSheet / 阴影.

不依赖 atlas 类. atlas_classes.py 和 loaders.py 都从这里取共享设施.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import pygame


ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"
SPRITES_DIR = ASSETS_DIR / "sprites"
UI_DIR = ASSETS_DIR / "ui"

# 世界 tile 像素尺寸 (横 × 纵, 4:3 比例).
# ps_ atlas cell = 64×96, tile = 64×48 → sprite 占 1×2 tile (身体 1 格 + 头部/装备上溢 1 格),
# 符合 SLG 标准 sprite-to-tile 比例. 640×480 屏幕 = 10×10 整数网格.
TILE_W = 64
TILE_H = 48

# 已知角色 atlas 默认尺寸 (大部分 384x384 = 4×6 of 64×96)
DEFAULT_CHAR_FRAME_SIZE = (64, 96)


# ----- 朝向 -----
class Direction(Enum):
    DOWN = (0, 1)
    LEFT = (-1, 0)
    RIGHT = (1, 0)
    UP = (0, -1)


def facing_to_direction(facing: tuple[int, int]) -> Direction:
    """战斗里用的 (dx, dy) 朝向 → Direction 枚举. 0 时优先 DOWN."""
    dx, dy = facing
    if dy > 0:  return Direction.DOWN
    if dy < 0:  return Direction.UP
    if dx < 0:  return Direction.LEFT
    if dx > 0:  return Direction.RIGHT
    return Direction.DOWN


# ----- color key -----
# 用 AUTO 让 load_image 在加载时采样左上角像素当 colorkey.
# 老约定 (ps_=黑, fm_=绿) 已废弃: 实测 ps_CSON100 / ps_CDIT100 等也是绿底,
# 名字前缀不可靠. 角色 atlas 的左上角几乎总是背景色, 自动采样更稳.
AUTO = "AUTO"


def load_image(
    path: Path,
    color_key: tuple[int, int, int] | None | str = AUTO,
) -> pygame.Surface:
    """加载 PCX/PNG, 应用色键并 convert 到 display 格式.

    color_key:
      AUTO  - 采样左上角像素作为透明色 (默认, 适用于角色 atlas)
      None  - 不设色键, 走 alpha 通道
      (r,g,b) - 显式指定透明色
    """
    surf = pygame.image.load(str(path))
    if color_key == AUTO:
        color_key = tuple(surf.get_at((0, 0)))[:3]
    if color_key is not None:
        surf = surf.convert() if pygame.display.get_surface() else surf
        surf.set_colorkey(color_key)
    else:
        surf = surf.convert_alpha() if pygame.display.get_surface() else surf
    return surf


# ----- 通用 sheet -----
class SpriteSheet:
    """把一张 atlas 按固定 frame_w × frame_h 切成网格. 透明色已应用在 surface.
    feet_anchor() 返回固定锚点 (ps_ 美术约定: 居中 + 脚靠近 y≈88).
    """

    def __init__(self, surface: pygame.Surface, frame_w: int, frame_h: int):
        self.surface = surface
        self.frame_w = frame_w
        self.frame_h = frame_h
        self.cols = surface.get_width() // frame_w
        self.rows = surface.get_height() // frame_h

    def __repr__(self) -> str:
        return (f"<SpriteSheet {self.surface.get_size()} "
                f"frame={self.frame_w}x{self.frame_h} "
                f"grid={self.cols}x{self.rows}>")

    def frame(self, col: int, row: int) -> pygame.Surface:
        """返回 (col, row) 那一帧的 subsurface (共享内存, 不要 modify)."""
        if not (0 <= col < self.cols and 0 <= row < self.rows):
            raise IndexError(f"frame ({col},{row}) out of grid {self.cols}x{self.rows}")
        rect = pygame.Rect(col * self.frame_w, row * self.frame_h,
                           self.frame_w, self.frame_h)
        return self.surface.subsurface(rect)

    def row_frames(self, row: int) -> list[pygame.Surface]:
        return [self.frame(c, row) for c in range(self.cols)]

    def feet_anchor(self, col: int, row: int) -> tuple[int, int]:
        """ps_ atlas 的每个 cell 美术已预先排版好 (居中 + 底部对齐).
        基准: cell 底沿对齐 tile 底沿 (anchor_y = frame_h - TILE_H/2).
        额外上移 12 px 让 sprite 视觉脚点落在阴影中心 (cell 底部留白 + 阴影画在 tile 中心)."""
        return (self.frame_w // 2, self.frame_h - TILE_H // 2 + 12)


# ----- 阴影 -----
# 原版预渲染阴影 (assets/ui/SHADOW.png 内 7 个递增椭圆 band, 按 unit 体型选用):
# band 0 最小 (虫/小怪), band 4 普通角色, band 6 最大 (boss).
# (x, y, w, h) 是 SHADOW.png 里每个 band 的子区, 颜色 = 纯黑 (0,2,7), 背景 colorkey (0,163,0).
SHADOW_BANDS: list[tuple[int, int, int, int]] = [
    (19, 28,  11,  3),
    (17, 47,  15,  5),
    (15, 66,  19,  7),
    (12, 85,  25,  9),
    (10, 104, 29, 11),
    ( 7, 122, 35, 15),
    ( 4, 141, 41, 17),
]
SHADOW_NORMAL = 4   # 普通玩家/敌人体型
SHADOW_BOSS = 6
_shadow_atlas: pygame.Surface | None = None
_shadow_cache: dict[tuple[int, int], pygame.Surface] = {}


def load_shadow(size_idx: int = SHADOW_NORMAL, alpha: int = 140) -> pygame.Surface:
    """加载原版 SHADOW.png 第 size_idx 号阴影 band, 整体 alpha 调到 alpha (0-255)."""
    global _shadow_atlas
    if _shadow_atlas is None:
        _shadow_atlas = pygame.image.load(str(UI_DIR / "SHADOW.png")).convert()
        _shadow_atlas.set_colorkey((0, 163, 0))
    key = (size_idx, alpha)
    if key not in _shadow_cache:
        x, y, w, h = SHADOW_BANDS[size_idx]
        band = _shadow_atlas.subsurface(pygame.Rect(x, y, w, h)).copy()
        band.set_colorkey((0, 163, 0))
        band.set_alpha(alpha)
        _shadow_cache[key] = band
    return _shadow_cache[key]
