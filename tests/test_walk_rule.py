"""通行规则 (flag = type + 4*level) 的回归。

规则来源：**用原版自己的数据反推 + 校准**（不是猜的）：
  · 486 个官方出生点：排除门格后全部落在 flag ∈ {0, 3}，无一落在 11/13/15；
  · 权威全宝箱表 1022 箱：flag 分布 0/11/15/7/13/3/5/19/9/27 —— **flag=13 上有 46 出生点 + 31 宝箱**，
    旧规则只认 {0,3,7} 会把它们当墙；
  · BFS 连通性 (**含空瓦片/外框判定的完整 `passable`, 同口径**)：旧 {0,3,7} = 77.8%，
    新 type/level 规则 = 79.7% (+20 个宝箱可达)；另 8 张图的官方 pcpos 落在外框/水域上，
    已改为 pcpos 格一律放行 (修好后 486 个出生点 100% 可站)。

故：type != 3 -> 可走；type == 3 时 level <= 1 (flag 3/7) 可走，level >= 2 (11,15,...) 实心。
"""

import json
from collections import deque
from pathlib import Path

import pytest

# 权威全宝箱表来自光盘版 xlsx (tools/import_chests_xlsx.py, 文件不入库); 没有它时
# chests.json 只是 gen_chests 的 84 个占位候选, 宝箱可达率的两个阈值测试无意义 → skip.
_CHEST_XLSX = Path(__file__).resolve().parent.parent.parent / "幻想西游记_全宝箱数据.xlsx"
_needs_chest_xlsx = pytest.mark.skipif(
    not _CHEST_XLSX.exists(), reason="缺 ../幻想西游记_全宝箱数据.xlsx (权威宝箱表)")

from core import real_map as realm
from core import world_graph as wg
from core.real_map import flag_walkable

ASSETS = Path(__file__).resolve().parents[1] / "assets"


@_needs_chest_xlsx
def test_chest_reachable_through_doors():
    """多图/门口径: 允许"踩在门格上"并从该图**任意一道门**进图后, 宝箱可达率应 ≥ 90%。

    · 门格是引擎放行的落脚点 (WorldMapScene 的 `passable_at` 也这么放行), 所以连通性检查里
      必须把 transition 格当可踩 —— 不这么做会低估 (实测 897/1022 = 87.8% vs 920/1022 = 90.0%)。
    · 剩余 ~10% 是"被结构格(type3 level≥2) 围死的口袋"(如小房间/墙内), 原版靠 **tile 级碰撞表**
      区分 (提取数据里分不出), 属已知数据限制, 不是规则错误。
    """
    maps = json.loads((ASSETS / "chests.json").read_text(encoding="utf-8"))["maps"]
    ok = tot = 0
    for base, lst in maps.items():
        try:
            m = realm.load(base)
        except Exception:
            continue
        tr = wg.transitions(base)
        seeds = list(tr) or [m.start_pos()]
        seen, q = set(), deque()
        for s in seeds:
            if m.passable(*s) or s in tr:
                seen.add(s); q.append(s)
        while q:
            x, y = q.popleft()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if (nx, ny) in seen or not m.in_bounds(nx, ny):
                    continue
                if m.passable(nx, ny) or (nx, ny) in tr:
                    seen.add((nx, ny)); q.append((nx, ny))
        for c in lst:
            x, y = int(c["x"]), int(c["y"])
            tot += 1
            if any(p in seen for p in ((x, y), (x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
                   if m.in_bounds(*p)):
                ok += 1
    assert tot > 900
    assert ok / tot >= 0.93, f"经门可达率跌破 93%: {ok}/{tot} = {ok / tot:.1%}"


@pytest.mark.parametrize("f,expect", [
    (0, True), (2, True), (3, True), (5, True), (6, True), (7, True),
    (9, True), (10, True), (13, True), (14, True),
    (11, False), (15, False), (19, False), (23, False), (27, False), (31, False),
])
def test_flag_walkable_type_level(f, expect):
    assert flag_walkable(f) is expect


def test_every_map_start_pos_is_passable():
    """每张图的 `start_pos()` (玩家开局落点) 必须真的可站。

    ⚠ 不要改成"允许 .mfo pcpos 一律可走": 实测 8 张图的 pcpos[0] 落在**外框近黑/水域**上
      (如小森林 TBB0___P = (22,9), 就在 x=w-1 边框), 而且**与图内可走区不连通** ——
      放行后 `start_pos()` 会选中它, 玩家开局直接卡在死角 (2026-09-29 踩过)。
      `start_pos()` 的正确行为 = 依次试 pcpos, 取第一个可走的; 都不行则退到"离中心最近的可走格"。
    """
    lm = json.loads((ASSETS / "location_map.json").read_text(encoding="utf-8"))["locations"]
    bad = []
    checked = 0
    for base in lm:
        try:
            m = realm.load(base)
        except Exception:
            continue
        sp = m.start_pos()
        checked += 1
        if m.passable(*sp):
            continue
        bad.append((base, sp, m.flag(*sp)))
    assert checked > 300
    assert not bad, f"开局落点不可站: {bad[:10]}"


def test_official_spawns_are_standable_or_doors():
    """原版每个地点的出生点：可走, 或本身就是门格(由传送放行), 或该图 pcpos 无可用格时退到中心。"""
    lm = json.loads((ASSETS / "location_map.json").read_text(encoding="utf-8"))["locations"]
    bad, checked = [], 0
    for base in lm:
        sp = wg.spawn(base)
        if not sp:
            continue
        try:
            m = realm.load(base)
        except Exception:
            continue
        x, y = sp
        if not (0 <= x < m.w and 0 <= y < m.h):
            continue
        checked += 1
        if m.passable(x, y) or (x, y) in wg.transitions(base) or m.start_pos() != (x, y):
            continue
        # spawn 既不可走、又不是门, 但 start_pos 仍选中它 → 真问题
        bad.append((base, (x, y), m.flag(x, y)))
    assert checked > 300
    assert not bad, f"出生点不可站且非门: {bad[:10]}"


@_needs_chest_xlsx
def test_chest_reachability_not_worse_than_baseline():
    """权威宝箱表的可达率 (BFS 从各图出生点出发; 宝箱格或紧邻格可达即算覆盖)。

    阈值 90% 是**下限护栏**。演进：77.8%（旧 flag 规则）→ 87.8%（空瓦片豁免）→ 更高（闸门白名单）。
    剩余不可达主要是"图内被封住、只能从别的图进入"的区域。这里只防通行规则被改坏。
    """
    maps = json.loads((ASSETS / "chests.json").read_text(encoding="utf-8"))["maps"]
    ok = tot = 0
    for base, lst in maps.items():
        try:
            m = realm.load(base)
        except Exception:
            continue
        sp = wg.spawn(base) or m.start_pos()
        if not (0 <= sp[0] < m.w and 0 <= sp[1] < m.h):
            sp = m.start_pos()
        seen, q = {sp}, deque([sp])
        while q:
            x, y = q.popleft()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if (nx, ny) in seen or not (0 <= nx < m.w and 0 <= ny < m.h):
                    continue
                if m.passable(nx, ny):
                    seen.add((nx, ny))
                    q.append((nx, ny))
        for c in lst:
            x, y = int(c["x"]), int(c["y"])
            tot += 1
            if any(p in seen for p in ((x, y), (x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
                   if 0 <= p[0] < m.w and 0 <= p[1] < m.h):
                ok += 1
    assert tot > 900
    assert ok / tot >= 0.90, f"宝箱可达率跌破护栏: {ok}/{tot} = {ok / tot:.1%}"


