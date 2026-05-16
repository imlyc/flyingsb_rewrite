"""角色普攻 aim 模板: 给定 unit + map, 计算攻击范围 + 给定 cursor 计算伤害范围.

术语 (跟 tactics.py 一致):
  攻击范围 (= pattern_fn): cursor 在 AIM 中可游走的格子集合.
  伤害范围 (= strike_fn):  cursor 确认时实际造成伤害的 tile 集合.

- pattern_fn(u, m) → set[(x, y)]
- strike_fn(u, cursor) → set[(x, y)]

每个角色一对. 未注册角色走默认 (攻击范围 = 面前 1 格 / 伤害范围 = cursor 单点).
"""

from __future__ import annotations

from core.battle.data import BattleMap, BattleUnit


def _perp(facing: tuple[int, int]) -> tuple[int, int]:
    """90° CCW (math) = pygame 屏幕上的垂直方向."""
    fx, fy = facing
    return (fy, -fx)


# ---------- pattern (cursor 可游走集合) ----------

def pattern_forward_line(u: BattleUnit, m: BattleMap, depth: int) -> set[tuple[int, int]]:
    """前方 1..depth 格."""
    fx, fy = u.facing
    out: set[tuple[int, int]] = set()
    for d in range(1, depth + 1):
        x, y = u.x + fx * d, u.y + fy * d
        if m.in_bounds(x, y):
            out.add((x, y))
    return out


def pattern_box(u: BattleUnit, m: BattleMap, depth: int, width: int) -> set[tuple[int, int]]:
    """前方 depth 格深 × width 格宽 (宽度必须奇数, 居中 facing 方向)."""
    fx, fy = u.facing
    px, py = _perp(u.facing)
    half = width // 2
    out: set[tuple[int, int]] = set()
    for d in range(1, depth + 1):
        for s in range(-half, half + 1):
            x = u.x + fx * d + px * s
            y = u.y + fy * d + py * s
            if m.in_bounds(x, y):
                out.add((x, y))
    return out


# ---------- strike (按下确认后实际伤害的 tile) ----------

def strike_single(u: BattleUnit, cursor: tuple[int, int]) -> set[tuple[int, int]]:
    return {cursor}


def strike_perpendicular_line(u: BattleUnit, cursor: tuple[int, int],
                              length: int) -> set[tuple[int, int]]:
    """过 cursor 的 facing 垂直方向 length 格 (奇数, 居中)."""
    px, py = _perp(u.facing)
    half = length // 2
    cx, cy = cursor
    return {(cx + px * s, cy + py * s) for s in range(-half, half + 1)}


# ---------- 角色注册 ----------
# 每个 entry: (pattern_fn(u, m), strike_fn(u, cursor)).
# 当前都走 default (= 面前 1 格 / 单点); 加角色专属攻击范围时在此 dict 加 entry.
AIM_PROFILES: dict[str, tuple] = {}


def get_aim_funcs(name: str):
    """未注册角色 fallback: 普攻面前 1 格, 单点伤害."""
    return AIM_PROFILES.get(name, (
        lambda u, m: pattern_forward_line(u, m, depth=1),
        strike_single,
    ))
