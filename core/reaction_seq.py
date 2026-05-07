"""受击 / 闪避 动画序列数据 (从 FlyingSB.exe 逆向得到).

来源: PTR_DAT_006557f0 (HIT) / PTR_DAT_00655960 (DODGE) at FlyingSB.exe
opcode 解码:
  0x0a06 = SET_FRAME   (atlas=6, frame_idx)  → 切到 atlas 06 的指定帧
  0x0a0b = MOVE        (dx, dy, _, ticks)    → 在 ticks 内位移; ticks=0 表示瞬间
  0x040e = END

帧索引在 atlas 06 (4 列 × 5 行) 内行优先: frame = row * 4 + col
  frame  0- 3 = row 0 (idle 呼吸帧 0) UP/DOWN/LEFT/RIGHT
  frame  4- 7 = row 1 (idle 呼吸帧 1)
  frame  8-11 = row 2 (轻击 — 此序列未使用)
  frame 12-15 = row 3 (闪避)
  frame 16-19 = row 4 (重击)

序列索引 [0..3] = 防守者面朝攻击者的方向 (0=UP, 1=DOWN, 2=LEFT, 3=RIGHT).
"""
from __future__ import annotations

# 每步: ('frame', idx) | ('move', dx_px, dy_px, ticks)
# tick 长度由 REACTION_TICK_MS 决定; 原版 DOS 时代约 30Hz, 我们用 40ms/tick 接近视频观感.
REACTION_TICK_MS = 40

HIT_SEQ: list[list[tuple]] = [
    # 0: defender 朝 UP (攻击者在上), 被推下
    [('frame', 16),
     ('move', 0,  4, 2),
     ('move', 0,  3, 3),
     ('move', 0,  2, 10),
     ('move', 0, -9, 0),     # 瞬间归位
     ('frame', 0)],
    # 1: defender 朝 DOWN, 被推上
    [('frame', 17),
     ('move', 0, -4, 2),
     ('move', 0, -3, 3),
     ('move', 0, -2, 10),
     ('move', 0,  9, 0),
     ('frame', 1)],
    # 2: defender 朝 LEFT, 被推右
    [('frame', 18),
     ('move',  4, 0, 2),
     ('move',  3, 0, 3),
     ('move',  2, 0, 10),
     ('move', -9, 0, 0),
     ('frame', 2)],
    # 3: defender 朝 RIGHT, 被推左
    [('frame', 19),
     ('move', -4, 0, 2),
     ('move', -3, 0, 3),
     ('move', -2, 0, 10),
     ('move',  9, 0, 0),
     ('frame', 3)],
]

DODGE_SEQ: list[list[tuple]] = [
    # 0: defender 朝 UP, 闪避向下 (5 段递减缓出 + 瞬归)
    [('frame', 12),
     ('move', 0,  6, 1),
     ('move', 0,  5, 1),
     ('move', 0,  4, 2),
     ('move', 0,  2, 3),
     ('move', 0,  1, 5),
     ('move', 0, -18, 0),
     ('frame', 0)],
    # 1: defender 朝 DOWN, 闪避向上 (原数据归位时还有 +4 dx 残留, 保留)
    [('frame', 13),
     ('move', 0, -6, 1),
     ('move', 0, -5, 1),
     ('move', 0, -4, 2),
     ('move', 0, -2, 3),
     ('move', 0, -1, 5),
     ('move', 4, 18, 0),
     ('frame', 1)],
    # 2: defender 朝 LEFT, 闪避向右
    [('frame', 14),
     ('move',  6, 0, 1),
     ('move',  5, 0, 1),
     ('move',  4, 0, 2),
     ('move',  2, 0, 3),
     ('move',  1, 0, 5),
     ('move', -18, 0, 0),
     ('frame', 2)],
    # 3: defender 朝 RIGHT, 闪避向左
    [('frame', 15),
     ('move', -6, 0, 1),
     ('move', -5, 0, 1),
     ('move', -4, 0, 2),
     ('move', -2, 0, 3),
     ('move', -1, 0, 5),
     ('move', 18, 0, 0),
     ('frame', 3)],
]


def facing_to_seq_index(facing: tuple[int, int]) -> int:
    dx, dy = facing
    if dy < 0: return 0   # UP
    if dy > 0: return 1   # DOWN
    if dx < 0: return 2   # LEFT
    return 3              # RIGHT


def atlas_frame_to_row_col(frame_idx: int) -> tuple[int, int]:
    """row-major 4 列 × 5 行 → (col, row)."""
    return frame_idx % 4, frame_idx // 4
