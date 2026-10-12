"""五指村那道带栏杆的木梯/桥应能走上去 (用户实测反馈)."""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from collections import deque

import pygame
import pytest

from core import real_map as realm


@pytest.fixture(scope="module")
def _pygame():
    pygame.init()
    pygame.display.set_mode((64, 64))
    yield


def test_wooden_bridge_is_walkable(_pygame):
    """木梯/桥在属性层与屋顶同码 (type3 level3), 靠 _WALK_OVER_TILES 白名单放行."""
    m = realm.load("TFI0___P")
    for (x, y) in [(22, 20), (22, 22), (22, 24), (22, 26), (23, 24), (23, 21)]:
        assert m.passable(x, y), f"木梯 ({x},{y}) 走不上去"
    # 从玩家报的位置能走到梯子两侧、梯顶与右侧草地
    sp = (21, 24)
    seen, q = {sp}, deque([sp])
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if (nx, ny) in seen or not m.in_bounds(nx, ny):
                continue
            if m.passable(nx, ny):
                seen.add((nx, ny)); q.append((nx, ny))
    for tgt in [(22, 24), (23, 24), (22, 18), (24, 24), (22, 26)]:
        assert tgt in seen, f"从 {sp} 走不到 {tgt}"


def test_doors_stay_reachable(_pygame):
    """⚠ 底线回归: 全游戏传送门必须基本都能走到.

    2026-09-28 试过用 "网格B 覆盖层!=0 → 不可走" 来挡"走上墙", 结果 **417/1146 个门走不到**
    (覆盖层也压在城镇地板/门口上), 已回退。基线约 92 个 (多为需先从别处进图的场景)。

    2026-09-29: ① 通行改成 flag 的 type/level 规则; ② 空瓦片启发式按"被官方数据当可站格用过"的
    瓦片做豁免 (`assets/void_tiles.json`) → **160 → 72** 个不可达。阈值收紧到 80。
    """
    from collections import deque
    from core import world_graph as wg
    unreachable = 0
    total = 0
    for base in wg.all_bases():
        tr = wg.transitions(base)
        if not tr:
            continue
        try:
            m = realm.load(base)
        except Exception:
            continue
        sp = wg.spawn(base) or m.start_pos()
        if not m.passable(*sp):
            sp = m.start_pos()
        seen = set()
        if m.passable(*sp):
            seen = {sp}
            q = deque([sp])
            while q:
                x, y = q.popleft()
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if (nx, ny) in seen or not m.in_bounds(nx, ny):
                        continue
                    if (nx, ny) in tr or m.passable(nx, ny):
                        seen.add((nx, ny)); q.append((nx, ny))
        for pos in tr:
            total += 1
            if pos not in seen:
                unreachable += 1
    assert unreachable <= 60, f"太多传送门走不到: {unreachable}/{total} (通行规则又改坏了?)"


def test_town_streets_stay_connected(_pygame):
    """新规则不能把城镇街道堵死: 雅士兰从街心出发应能走到图的大部分可走格."""
    from collections import deque
    m = realm.load("TAS0___P")
    sp = (20, 30)
    assert m.passable(*sp)
    seen, q = {sp}, deque([sp])
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if (nx, ny) in seen or not m.in_bounds(nx, ny):
                continue
            if m.passable(nx, ny):
                seen.add((nx, ny)); q.append((nx, ny))
    walk = sum(1 for y in range(m.h) for x in range(m.w) if m.passable(x, y))
    assert len(seen) >= walk * 0.9, f"街道不连通: 可走 {walk}, 只到 {len(seen)}"


def test_walls_and_roofs_still_solid(_pygame):
    """白名单只放行桥/梯瓦片, 墙与屋顶必须仍然实心 (别为了修桥把穿墙放回来)."""
    m = realm.load("TFI0___P")
    assert not m.passable(15, 28) or m.flag(15, 28) in (0, 3, 7)   # 底部墙体 11/15
    solid = [(x, y) for y in range(m.h) for x in range(m.w)
             if not m.passable(x, y)]
    assert len(solid) > 200, "可走区域异常膨胀 (疑似把墙放开了)"
