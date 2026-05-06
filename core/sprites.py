"""Sprite atlas 加载与切帧.

原版 sprite 命名约定:
  ps_*  来自 ase_ps.dll, 黑底色键 (0,0,0) 透明
  fm_*  来自 ase_fm.dll, 绿底色键 (0,255,0) 透明 — 多为特效/重影
  其它  无色键 (UI / 不透明 tileset)

角色 atlas 主流尺寸 384×384, 切 4 行 × 6 列 = 24 帧, 单帧 64×96:
  行 0 = 朝上 (背对相机),  行 1 = 朝下 (面向相机)
  行 2 = 朝右,             行 3 = 朝左 (经验值, 个别角色可能反)
  列 0..5 = 该朝向的动画帧 (待机 / 走 / 攻击 等)

朝向行映射为 *约定值*; 后续可改 DIRECTION_ROWS 适配单个角色.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pygame

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
SPRITES_DIR = ASSETS_DIR / "sprites"
UI_DIR = ASSETS_DIR / "ui"

# ----- 朝向 -----
class Direction(Enum):
    DOWN = (0, 1)
    LEFT = (-1, 0)
    RIGHT = (1, 0)
    UP = (0, -1)


# 角色 atlas 4 行的朝向顺序 (verify_directions.png 实测确认):
# row 0 = UP (背对), row 1 = DOWN (面对), row 2 = LEFT, row 3 = RIGHT.
DEFAULT_DIRECTION_ROWS: dict[Direction, int] = {
    Direction.UP:    0,
    Direction.DOWN:  1,
    Direction.LEFT:  2,
    Direction.RIGHT: 3,
}


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
    """把一张 atlas 按固定 frame_w × frame_h 切成网格. 透明色已应用在 surface."""

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


# ----- 角色 atlas -----
# 实测 ps_CSON100 row 1 (DOWN): col 0 站立, col 1 迈步, col 2..4 备用站姿,
# col 5 转身 45°. 即走路循环只在前 2 列. 其它 atlas 暂沿用同样约定.
DEFAULT_WALK_FRAMES = 2


@dataclass
class CharacterSprite:
    """4 朝向 × N 帧 的角色动画 atlas. anim_idx 走路帧只取前 walk_frames 列."""
    sheet: SpriteSheet
    direction_rows: dict[Direction, int]
    walk_frames: int = DEFAULT_WALK_FRAMES

    @property
    def frame_count(self) -> int:
        return self.sheet.cols

    def frame(self, direction: Direction, anim_idx: int = 0) -> pygame.Surface:
        row = self.direction_rows[direction]
        col = anim_idx % self.walk_frames
        return self.sheet.frame(col, row)

    def frame_for_facing(self, facing: tuple[int, int], anim_idx: int = 0) -> pygame.Surface:
        return self.frame(facing_to_direction(facing), anim_idx)


# 已知角色 atlas 默认尺寸 (大部分 384x384 = 4×6 of 64×96)
DEFAULT_CHAR_FRAME_SIZE = (64, 96)


def load_character_sprite(
    resource_name: str,
    frame_w: int = DEFAULT_CHAR_FRAME_SIZE[0],
    frame_h: int = DEFAULT_CHAR_FRAME_SIZE[1],
    direction_rows: dict[Direction, int] | None = None,
) -> CharacterSprite:
    """从 assets/sprites/<resource_name>.pcx 加载角色 atlas.

    名字通常带 'ps_' / 'fm_' 前缀, 决定色键. 例: 'ps_CAMAZ000'.
    """
    path = SPRITES_DIR / f"{resource_name}.pcx"
    if not path.exists():
        raise FileNotFoundError(path)
    surf = load_image(path, color_key=AUTO)
    sheet = SpriteSheet(surf, frame_w, frame_h)
    return CharacterSprite(
        sheet=sheet,
        direction_rows=direction_rows or DEFAULT_DIRECTION_ROWS,
    )


# ----- 缓存: 同一资源多次加载只读一次磁盘 -----
_CACHE: dict[str, CharacterSprite] = {}


def get_character_sprite(resource_name: str, **kwargs) -> CharacterSprite:
    if resource_name not in _CACHE:
        _CACHE[resource_name] = load_character_sprite(resource_name, **kwargs)
    return _CACHE[resource_name]


def clear_cache() -> None:
    _CACHE.clear()
