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
def detect_feet_anchor(
    surface: pygame.Surface,
    x: int, y: int, w: int, h: int,
    colorkey: tuple[int, int, int],
) -> tuple[int, int]:
    """扫描 sprite 区域, 自动定位脚点 anchor.
    feet_y = 最底部非 colorkey 像素的 y + 1 (= baseline 像素行下沿).
    feet_x = 底部 4 行内非 colorkey 像素的 x 平均值 (= 脚部中心).
    若全空返回 (w//2, h).
    """
    bottom_y = -1
    for off_y in range(h - 1, -1, -1):
        for off_x in range(w):
            if surface.get_at((x + off_x, y + off_y))[:3] != colorkey:
                bottom_y = off_y
                break
        if bottom_y >= 0:
            break
    if bottom_y < 0:
        return (w // 2, h)
    xs = []
    for sy in range(max(0, bottom_y - 3), bottom_y + 1):
        for sx in range(w):
            if surface.get_at((x + sx, y + sy))[:3] != colorkey:
                xs.append(sx)
    feet_x = sum(xs) // len(xs) if xs else w // 2
    return (feet_x, bottom_y + 1)


class SpriteSheet:
    """把一张 atlas 按固定 frame_w × frame_h 切成网格. 透明色已应用在 surface.
    feet_anchor(col, row) lazily 检测每帧的脚点位置 (用 colorkey 之上最底像素).
    """

    def __init__(self, surface: pygame.Surface, frame_w: int, frame_h: int):
        self.surface = surface
        self.frame_w = frame_w
        self.frame_h = frame_h
        self.cols = surface.get_width() // frame_w
        self.rows = surface.get_height() // frame_h
        self._feet_cache: dict[tuple[int, int], tuple[int, int]] = {}

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
        """返回该 (col, row) 帧的原始脚点检测. 不做共享 — 调用方决定如何共享 anchor.
        典型用法: CharacterSprite 按 row (=方向) 共享, IdleSprite 按 col (=方向) 共享.
        """
        if not (0 <= col < self.cols and 0 <= row < self.rows):
            return (self.frame_w // 2, self.frame_h)
        key = (col, row)
        if key not in self._feet_cache:
            ck = self.surface.get_colorkey()
            ck_rgb = ck[:3] if ck is not None else (0, 0, 0)
            self._feet_cache[key] = detect_feet_anchor(
                self.surface, col * self.frame_w, row * self.frame_h,
                self.frame_w, self.frame_h, ck_rgb,
            )
        return self._feet_cache[key]


# ----- 角色 atlas -----
# 实测 ps_CSON100 / 用户确认:
#   col 0..4 = 走路 5 帧 (cols 2 与 4 互为对称的迈步)
#   col 5    = 转向 45° 过渡帧
# 每个方向的 col 5 服务一个 90° 转向对:
#   UP    col5 = UP↔RIGHT 过渡
#   LEFT  col5 = UP↔LEFT  过渡
#   DOWN  col5 = DOWN↔LEFT 过渡
#   RIGHT col5 = DOWN↔RIGHT 过渡
DEFAULT_WALK_FRAMES = 5
TURN_FRAME_COL = 5

# 飞行单位: walk atlas 只有 4 帧 (col 4 空), 且 idle atlas (06) 行 0/1 空白 —
# 因为飞行=待机=移动都是同一组扇翅膀帧. 渲染时:
#   - walk_frames 用 4 (避免循环到空白 col 4)
#   - 待机不读 06 行 0/1, 改成在 walk atlas 上以 idle 节奏循环 (扇翅膀)
#   - reaction 仍读 06 行 2/3/4 (那几行有内容)
FLYING_WALK_KEYS: set[str] = {"ps_CCROW00"}


def is_flying_sprite(walk_key: str) -> bool:
    return walk_key in FLYING_WALK_KEYS

# 90° 转向对 → 该过渡帧所在的 atlas 行 (用 Direction 枚举表示)
TURN_TRANSITION_DIR: dict[frozenset[Direction], Direction] = {
    frozenset({Direction.UP,   Direction.RIGHT}): Direction.UP,
    frozenset({Direction.UP,   Direction.LEFT}):  Direction.LEFT,
    frozenset({Direction.DOWN, Direction.LEFT}):  Direction.DOWN,
    frozenset({Direction.DOWN, Direction.RIGHT}): Direction.RIGHT,
}


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

    def turn_frame(
        self, from_dir: Direction, to_dir: Direction
    ) -> pygame.Surface | None:
        """两 90° 朝向之间的过渡帧 (col 5). 同向或 180° 反向返回 None."""
        if from_dir == to_dir:
            return None
        owner = TURN_TRANSITION_DIR.get(frozenset({from_dir, to_dir}))
        if owner is None:
            return None  # 180° 翻转, 无过渡帧
        row = self.direction_rows[owner]
        return self.sheet.frame(TURN_FRAME_COL, row)

    def feet_for_direction(self, direction: Direction) -> tuple[int, int]:
        """返回该方向的统一 anchor (从 col=0 idle 站立姿态检测, 同方向所有帧共用).
        避免走路 cycle 因每帧 feet x 检测略有差异而导致 sprite 左右晃.
        """
        row = self.direction_rows[direction]
        return self.sheet.feet_anchor(0, row)

    def feet_for_facing(self, facing: tuple[int, int]) -> tuple[int, int]:
        return self.feet_for_direction(facing_to_direction(facing))


# ----- 待机 (idle) atlas -----
# atlas 索引 06 布局 (实测确认):
#   256×480 = 4 列 × 5 行, 单帧 64×96
#   列 = 朝向 (UP=0, DOWN=1, LEFT=2, RIGHT=3)
#   行 0/1 = 待机呼吸两帧
#   行 2 = 受到轻击 (小幅缩起 / 前倾)
#   行 3 = 闪避 miss (侧身 / 后仰 / 下蹲让开)
#   行 4 = 受到重击 (大幅反应 / 扑倒)
DEFAULT_IDLE_DIRECTION_COLS: dict[Direction, int] = {
    Direction.UP:    0,
    Direction.DOWN:  1,
    Direction.LEFT:  2,
    Direction.RIGHT: 3,
}
IDLE_FRAME_COUNT = 2

# row 2/3/4 的语义键
REACTION_LIGHT = "light"
REACTION_DODGE = "dodge"
REACTION_HEAVY = "heavy"
REACTION_ROWS = {REACTION_LIGHT: 2, REACTION_DODGE: 3, REACTION_HEAVY: 4}


@dataclass
class IdleSprite:
    """4 朝向 × 5 行的 atlas 06: 呼吸两帧 + 轻击/闪避/重击 各 1 帧."""
    sheet: SpriteSheet
    direction_cols: dict[Direction, int]

    def frame(self, direction: Direction, phase: int = 0) -> pygame.Surface:
        col = self.direction_cols[direction]
        row = phase % IDLE_FRAME_COUNT
        return self.sheet.frame(col, row)

    def frame_for_facing(self, facing: tuple[int, int], phase: int = 0) -> pygame.Surface:
        return self.frame(facing_to_direction(facing), phase)

    def reaction_frame(self, direction: Direction, kind: str) -> pygame.Surface:
        """根据 kind 取受击/闪避帧 (kind ∈ REACTION_ROWS)."""
        return self.sheet.frame(self.direction_cols[direction], REACTION_ROWS[kind])

    def reaction_for_facing(self, facing: tuple[int, int], kind: str) -> pygame.Surface:
        return self.reaction_frame(facing_to_direction(facing), kind)

    def feet_for_direction(self, direction: Direction) -> tuple[int, int]:
        """返回该方向的统一 anchor (idle row 0 检测; 同方向所有 idle/受击/闪避帧共用)."""
        col = self.direction_cols[direction]
        return self.sheet.feet_anchor(col, 0)

    def feet_for_facing(self, facing: tuple[int, int]) -> tuple[int, int]:
        return self.feet_for_direction(facing_to_direction(facing))


def idle_key_from_walk_key(walk_key: str) -> str:
    """'ps_CSON100' -> 'ps_CSON106';  'ps_CMIRO00' -> 'ps_CMIRO06' (末两位换成 '06')."""
    return walk_key[:-2] + "06"


def weakened_key_from_walk_key(walk_key: str) -> str:
    """'ps_CSON100' -> 'ps_CSON104'; ps_*04 atlas 是 HP<40% 虚弱态 + 第 5 行死亡帧."""
    return walk_key[:-2] + "04"


# ---------- ps_*04 虚弱/死亡 atlas ----------
# 192×480 = 3 列 × 5 行, 单帧 64×96. 来自 exe FUN_004c2492 case 0 weakened 分支:
#   行 0..3 = 4 朝向 (UP/DN/LF/RT), 每行 3 帧
#     - 帧 0 = 静止/初始姿势 (虚弱态不用, 留给特殊场景)
#     - 帧 1 / 帧 2 = ping-pong 动画 (HP<40% 时按周期切换)
#   行 4 = 死亡帧 (3 帧, 玩家躺尸 / 敌人闪烁消失用, 实现待 death 阶段)
WEAKENED_DIRECTION_ROWS: dict[Direction, int] = {
    Direction.UP:    0,
    Direction.DOWN:  1,
    Direction.LEFT:  2,
    Direction.RIGHT: 3,
}
WEAKENED_PING_PONG_COLS = (1, 2)   # frame 0 reserved
WEAKENED_DEATH_ROW = 4              # row 4 = 2 帧死亡序列 (cols 0=倒下中, 1=躺平; col 2 atlas 空白没素材)
WEAKENED_DEATH_FRAMES = 2           # 仅 cols 0/1 有内容


@dataclass
class WeakenedSprite:
    """ps_*04 atlas wrapper: 4 朝向 ping-pong 帧 + row 4 死亡帧."""
    sheet: SpriteSheet
    direction_rows: dict[Direction, int]

    def frame(self, direction: Direction, phase: int = 0) -> pygame.Surface:
        row = self.direction_rows[direction]
        col = WEAKENED_PING_PONG_COLS[phase % len(WEAKENED_PING_PONG_COLS)]
        return self.sheet.frame(col, row)

    def frame_for_facing(self, facing: tuple[int, int], phase: int = 0) -> pygame.Surface:
        return self.frame(facing_to_direction(facing), phase)

    def death_frame(self, idx: int) -> pygame.Surface:
        """row 4 frame (idx 0..1, exe frames 12/13). 0 = 倒下中, 1 = 躺平 (corpse pose).
        col 2 atlas 空白, 没素材."""
        return self.sheet.frame(idx % WEAKENED_DEATH_FRAMES, WEAKENED_DEATH_ROW)

    def death_anchor(self, idx: int = 1) -> tuple[int, int]:
        """corpse 帧的 body 中心 anchor (= 让躺尸居中填满 tile, 不像站立姿势那样用脚点).
        扫像素找非透明 BBox, 取中心. lazily cached."""
        if not hasattr(self, '_death_anchor_cache'):
            self._death_anchor_cache = {}
        if idx not in self._death_anchor_cache:
            fr = self.death_frame(idx).convert_alpha()
            min_x = fr.get_width(); max_x = 0
            min_y = fr.get_height(); max_y = 0
            for x in range(fr.get_width()):
                for y in range(fr.get_height()):
                    if fr.get_at((x, y))[3] > 0:
                        if x < min_x: min_x = x
                        if x > max_x: max_x = x
                        if y < min_y: min_y = y
                        if y > max_y: max_y = y
            if max_x < min_x:   # 空帧 fallback
                self._death_anchor_cache[idx] = (fr.get_width() // 2, fr.get_height() // 2)
            else:
                self._death_anchor_cache[idx] = ((min_x + max_x) // 2, (min_y + max_y) // 2)
        return self._death_anchor_cache[idx]

    def feet_for_direction(self, direction: Direction) -> tuple[int, int]:
        """anchor 检测 col=1 row[direction] (ping-pong 第一帧, 同方向所有帧共用)."""
        row = self.direction_rows[direction]
        return self.sheet.feet_anchor(WEAKENED_PING_PONG_COLS[0], row)

    def feet_for_facing(self, facing: tuple[int, int]) -> tuple[int, int]:
        return self.feet_for_direction(facing_to_direction(facing))


_WEAKENED_CACHE: dict[str, WeakenedSprite] = {}


def get_weakened_sprite(resource_name: str) -> WeakenedSprite:
    if resource_name not in _WEAKENED_CACHE:
        path = SPRITES_DIR / f"{resource_name}.pcx"
        if not path.exists():
            raise FileNotFoundError(path)
        surf = load_image(path, color_key=AUTO)
        # 显式 64×96 (= DEFAULT_CHAR_FRAME_SIZE), atlas 自动算 cols×rows = 3×5
        sheet = SpriteSheet(surf, DEFAULT_CHAR_FRAME_SIZE[0], DEFAULT_CHAR_FRAME_SIZE[1])
        _WEAKENED_CACHE[resource_name] = WeakenedSprite(
            sheet=sheet,
            direction_rows=WEAKENED_DIRECTION_ROWS,
        )
    return _WEAKENED_CACHE[resource_name]


_IDLE_CACHE: dict[str, IdleSprite] = {}


def get_idle_sprite(resource_name: str) -> IdleSprite:
    if resource_name not in _IDLE_CACHE:
        path = SPRITES_DIR / f"{resource_name}.pcx"
        if not path.exists():
            raise FileNotFoundError(path)
        surf = load_image(path, color_key=AUTO)
        sheet = SpriteSheet(surf, DEFAULT_CHAR_FRAME_SIZE[0], DEFAULT_CHAR_FRAME_SIZE[1])
        _IDLE_CACHE[resource_name] = IdleSprite(
            sheet=sheet,
            direction_cols=DEFAULT_IDLE_DIRECTION_COLS,
        )
    return _IDLE_CACHE[resource_name]


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
        cs = load_character_sprite(resource_name, **kwargs)
        if is_flying_sprite(resource_name):
            cs.walk_frames = 4   # col 4 空白, 只循环 cols 0-3
        _CACHE[resource_name] = cs
    return _CACHE[resource_name]


def clear_cache() -> None:
    _CACHE.clear()


# ----- fm_ atlas (攻击/特效) -----
# 逆向得到的真实数据: 每帧有显式 BBox (x, y, w, h) + 锚点 (ax, ay).
# fm atlas 不是均匀网格! 帧大小因姿态变化, 用逐帧 BBox 才能取出干净 sprite.
# 数据在 core/fm_frames.py (6610 帧, 334 个 atlas, 从 FlyingSB.exe 0x5bf8a8 表逆向).
_FM_SURF_CACHE: dict[str, pygame.Surface] = {}


# ---------- SBTLFONT 伤害/MISS 数字字体 ----------
# fm_SBTLFONT.pcx (130x56, 52 帧 unique BBox, 来自 fm_frames.SBTLFONT).
# 来源 exe FUN_004d05d8 + FUN_004d074e: 把 char (ASCII) 转 frame_idx.
#   FUN_004d074e 路径 (mass-spawn): frame_idx = char - 0x30 → 数字 '0'..'9' = frames 0..9
#   FUN_004d0488 路径 (drip-spawn): frame_idx = char - 0x23 → '0'..'9' = frames 13..22
# 我们用 drip 路径 (frames 13-22) 作为标准伤害数字, 跟用户观察一致.
# MISS: exe 用 chars 0x3a/0x3b/0x3c/0x3c (-0x23) = frames 23/24/25/25 (字母 'MISS' 在 atlas 后段)
SBTLFONT_DIGIT_BASE_FRAME = 13                         # row 1 cols 0-9 = 红色伤害数字 (跟 MISS 同行同色)
SBTLFONT_MISS_FRAMES = (23, 24, 25, 25)                # row 1 cols 10-12 = 红色 M/I/S/S
SBTLFONT_DAMAGE_BASE_FRAME = SBTLFONT_DIGIT_BASE_FRAME # 别名: 伤害数字也是红色 (= 跟 MISS 一致)


def get_sbtlfont_surface() -> pygame.Surface:
    return get_fm_surface("fm_SBTLFONT")


def sbtlfont_frame(char_or_digit: int) -> tuple[pygame.Surface, int, int]:
    """digit 0..9 → atlas frame 13..22; 也可传 frame index 直接取.
    返回 (subsurface, render_anchor_x, render_anchor_y) — anchor 从 fm_frames 取."""
    from core.fm_frames import FM_FRAMES
    frame_idx = char_or_digit if char_or_digit >= 13 else SBTLFONT_DIGIT_BASE_FRAME + char_or_digit
    bbox_data = FM_FRAMES.get("sbtlfont")
    if not bbox_data or frame_idx >= len(bbox_data):
        raise IndexError(f"sbtlfont frame {frame_idx} out of range")
    fx, fy, fw, fh, ax, ay = bbox_data[frame_idx]
    surf = get_sbtlfont_surface().subsurface(pygame.Rect(fx, fy, fw, fh))
    return surf, ax, ay


def get_fm_surface(resource_name: str) -> pygame.Surface:
    """加载 fm_ atlas 大图. 帧从 fm_frames.FM_FRAMES 取 BBox 子表面."""
    if resource_name not in _FM_SURF_CACHE:
        path = SPRITES_DIR / f"{resource_name}.pcx"
        if not path.exists():
            raise FileNotFoundError(path)
        _FM_SURF_CACHE[resource_name] = load_image(path, color_key=AUTO)
    return _FM_SURF_CACHE[resource_name]
