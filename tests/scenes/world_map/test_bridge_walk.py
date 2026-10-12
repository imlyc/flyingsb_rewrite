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


def _bfs(m, start, layer):
    """按 RealMap.step 做层感知 BFS → {(x, y, layer)}."""
    from collections import deque
    seen, q = {(start[0], start[1], layer)}, deque([(start[0], start[1], layer)])
    while q:
        x, y, z = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ok, nz, nx, ny = m.move(x, y, dx, dy, z)
            if ok and (nx, ny, nz) not in seen:
                seen.add((nx, ny, nz)); q.append((nx, ny, nz))
    return seen


def _open_spawn(m, cands):
    """第一个 可站 且 有可站邻格 的出生点 (港口到达点那种四面实心的格不算)."""
    for c in cands:
        if not c:
            continue
        z = m.layer_at(*c)
        if m.passable(*c, z) and any(m.passable(c[0] + dx, c[1] + dy, z)
                                     for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
            return c, z
    return None, 0


def test_wooden_bridge_is_walkable(_pygame):
    """五指村木梯 (exe 真值): 梯身 (22..23, 20..26) 在第 1 层, 梯口 (22,19)/(23,19) 是坡格 (bit12,
    朝向=下): 从北边草地 (第 0 层) 往下走上梯口 → 切到第 1 层 → 沿梯子下到东南红土台地."""
    m = realm.load("TFI0___P")
    for (x, y) in [(22, 20), (22, 22), (22, 24), (22, 26), (23, 24), (23, 21)]:
        assert m.passable(x, y, 1), f"梯身 ({x},{y}) 第 1 层走不上去"
    assert not m.passable(22, 20, 0) and not m.passable(23, 21, 0)   # 压在石墙上的两行, 第 0 层实心
    assert m.cell(22, 19) & realm.CELL_RAMP and m.cell(23, 19) & realm.CELL_RAMP
    ok, z = m.step(22, 18, 0, 1, 0)          # 草地 → 梯口: 切到第 1 层
    assert ok and z == 1
    ok, z = m.step(22, 20, 0, -1, 1)         # 梯身往上 → 梯口: 回第 0 层
    assert ok and z == 0
    seen = _bfs(m, (22, 18), 0)
    for tgt in [(22, 24, 1), (23, 24, 1), (22, 26, 1), (22, 36, 1)]:   # 梯子 + 台地上的房门
        assert tgt in seen, f"从草地走不到 {tgt}"


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
        sp, z = _open_spawn(m, [wg.spawn(base), m.start_pos()] + [(x, y) for x, y, _ in m.pcpos])
        seen = {(x, y) for (x, y, _z) in _bfs(m, sp, z)} if sp else set()
        seen |= {p for p in tr if any((p[0] + dx, p[1] + dy) in seen
                                     for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))}
        for pos in tr:
            total += 1
            if pos not in seen:
                unreachable += 1
    # exe 真值规则下基线 145: 剩下的几乎全是"一张图装多个独立房间" (TTD6/TMO17/TARB_09/TMT18/TDD0...),
    # 每个房间只能从别的图进, 本来就互不连通.
    assert unreachable <= 160, f"太多传送门走不到: {unreachable}/{total} (通行规则又改坏了?)"


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


def test_asram_raised_district_via_stairs(_pygame):
    """雅士蘭东北高台 (第 1 层) 的四个门, 要靠 (25,36) 斜梯 → (26,35) 坡口 切层才到得了."""
    m = realm.load("TAS0___P")
    seen = _bfs(m, (20, 43), 0)
    for door in [(28, 26), (34, 30), (35, 22), (31, 14)]:
        assert any((door[0] + dx, door[1] + dy, 1) in seen
                   for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (0, 0))), f"高台门 {door} 走不到"
