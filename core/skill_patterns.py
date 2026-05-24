"""技能 AOE pattern: skill_id → cursor walkable / damage tile 集合.

数据链 (exe 真值, dump 在 reverse_engineering/{skill0,static_pat}.txt):
    skill_id  → SKILL_TEMPLATE[skill_id] = tmpl_idx
    tmpl_idx  → ACTION_TEMPLATES[tmpl_idx] = (p1, p2, ax, ay)
    p1        → PATTERN_SET1[p1] 11×11 grid, cell==2 ⇒ cursor 可走
    p2        → PATTERN_SET2[p2] 11×11 grid, cell&4 ⇒ damage tile
    anchor    → (ax, ay) 似为投射物/特效 spawn 偏移; 不进 AOE 计算

Grid 中心 (row=5, col=5) = 对应"锚点 entity"位置:
- set1: 中心 = unit 自己 (cursor 相对 unit 偏移)
- set2: 中心 = cursor (damage 相对 cursor 偏移)

Grid 按 exe 默认 facing UP=(0,-1) 排布. 当前 unit facing 不同时按下式旋转:
    local (dx, dy) under up  →  world = (-dy)*(fx,fy) + dx*(-fy,fx)
"""

from __future__ import annotations

from core.skill_patterns_data import (
    ACTION_TEMPLATES,
    PATTERN_SET1,
    PATTERN_SET2,
    SKILL_TEMPLATE,
)
from core.battle.data import BattleMap, BattleUnit

GRID_SIZE = 11
GRID_CENTER = 5


def _rotate(dx: int, dy: int, facing: tuple[int, int]) -> tuple[int, int]:
    """Rotate (dx, dy) — expressed under exe default facing up (0,-1) — to `facing` frame."""
    fx, fy = facing
    # forward axis: -dy * facing; side axis: dx * perpendicular_CW(facing) = dx * (-fy, fx)
    return (-dy * fx + dx * (-fy), -dy * fy + dx * fx)


def _grid_cells(grid: tuple[tuple[int, ...], ...], match: int) -> list[tuple[int, int]]:
    """Return local (dx, dy) offsets where `cell & match` is truthy."""
    out: list[tuple[int, int]] = []
    for row in range(GRID_SIZE):
        for col in range(GRID_SIZE):
            if grid[row][col] & match:
                out.append((col - GRID_CENTER, row - GRID_CENTER))
    return out


def skill_template_idx(skill_id: int) -> int | None:
    return SKILL_TEMPLATE.get(skill_id)


def compute_skill_pattern(u: BattleUnit, m: BattleMap, skill_id: int) -> set[tuple[int, int]]:
    """AIM 阶段 cursor 可游走的 tile 集合 (相对 unit, 按 facing 旋转)."""
    tmpl_idx = SKILL_TEMPLATE.get(skill_id)
    if tmpl_idx is None or tmpl_idx >= len(ACTION_TEMPLATES):
        return set()
    p1 = ACTION_TEMPLATES[tmpl_idx][0]
    grid = PATTERN_SET1[p1]
    out: set[tuple[int, int]] = set()
    for dx, dy in _grid_cells(grid, 2):
        wx, wy = _rotate(dx, dy, u.facing)
        x, y = u.x + wx, u.y + wy
        if m.in_bounds(x, y):
            out.add((x, y))
    return out


def compute_skill_strike(
    u: BattleUnit, cursor: tuple[int, int], skill_id: int
) -> set[tuple[int, int]]:
    """确认 cursor 后实际命中的 tile 集合 (相对 cursor, 按 facing 旋转)."""
    tmpl_idx = SKILL_TEMPLATE.get(skill_id)
    if tmpl_idx is None or tmpl_idx >= len(ACTION_TEMPLATES):
        return {cursor}
    p2 = ACTION_TEMPLATES[tmpl_idx][1]
    grid = PATTERN_SET2[p2]
    cx, cy = cursor
    out: set[tuple[int, int]] = set()
    for dx, dy in _grid_cells(grid, 4):
        wx, wy = _rotate(dx, dy, u.facing)
        out.add((cx + wx, cy + wy))
    return out
