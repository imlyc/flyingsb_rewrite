"""ps_ atlas 包装类: CharacterSprite (走路) / IdleSprite (待机 06) / WeakenedSprite (虚弱+死亡 04).

共享 SpriteSheet, 各自暴露 frame() / frame_for_facing() / feet_for_facing().
"""

from __future__ import annotations

from dataclasses import dataclass

import pygame

from core.sprites.base import Direction, SpriteSheet, facing_to_direction


# ----- 角色 walk atlas -----
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

# 角色 atlas 4 行的朝向顺序 (verify_directions.png 实测确认):
# row 0 = UP (背对), row 1 = DOWN (面对), row 2 = LEFT, row 3 = RIGHT.
DEFAULT_DIRECTION_ROWS: dict[Direction, int] = {
    Direction.UP:    0,
    Direction.DOWN:  1,
    Direction.LEFT:  2,
    Direction.RIGHT: 3,
}

# 90° 转向对 → 该过渡帧所在的 atlas 行 (用 Direction 枚举表示)
TURN_TRANSITION_DIR: dict[frozenset[Direction], Direction] = {
    frozenset({Direction.UP,   Direction.RIGHT}): Direction.UP,
    frozenset({Direction.UP,   Direction.LEFT}):  Direction.LEFT,
    frozenset({Direction.DOWN, Direction.LEFT}):  Direction.DOWN,
    frozenset({Direction.DOWN, Direction.RIGHT}): Direction.RIGHT,
}

# 飞行单位: walk atlas 只有 4 帧 (col 4 空), 且 idle atlas (06) 行 0/1 空白 —
# 因为飞行=待机=移动都是同一组扇翅膀帧. 渲染时:
#   - walk_frames 用 4 (避免循环到空白 col 4)
#   - 待机不读 06 行 0/1, 改成在 walk atlas 上以 idle 节奏循环 (扇翅膀)
#   - reaction 仍读 06 行 2/3/4 (那几行有内容)
FLYING_WALK_KEYS: set[str] = {"ps_CCROW00"}


def is_flying_sprite(walk_key: str) -> bool:
    return walk_key in FLYING_WALK_KEYS


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
#   行 4 = 死亡帧 (3 帧, 玩家躺尸 / 敌人闪烁消失用)
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
        """corpse 帧 anchor — 跟 feet_anchor 用同一个固定锚点 (ps_ 美术约定:
        躺尸帧也按"水平居中 + 底部对齐"摆放)."""
        return self.sheet.feet_anchor(0, 0)

    def feet_for_direction(self, direction: Direction) -> tuple[int, int]:
        """anchor 检测 col=1 row[direction] (ping-pong 第一帧, 同方向所有帧共用)."""
        row = self.direction_rows[direction]
        return self.sheet.feet_anchor(WEAKENED_PING_PONG_COLS[0], row)

    def feet_for_facing(self, facing: tuple[int, int]) -> tuple[int, int]:
        return self.feet_for_direction(facing_to_direction(facing))
