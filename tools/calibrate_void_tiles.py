"""校准"空瓦片"启发式 + 生成"闸门瓦片"白名单 —— **全部用原版自己的数据**。

两件事：
 (A) `exempt` 空瓦片豁免：`_detect_void_tiles` / `_detect_black_tiles` 是按颜色猜的
     (品红=色键、偏蓝=水、均匀近黑=空)，会把真实可站的地板误判成空。若某瓦片出现在
     **门格 / 出生格 / .mfo pcpos / 权威宝箱表** 这些"原版必须能站"的格上，就把它从该
     tileset 的 `_void`/`_black` 里豁免。
 (B) `walk_over` 闸门白名单：有些**挡住权威宝箱唯一通路**的结构格（type3 level≥2），
     在原版其实是可跨过的门洞/门槛（提取数据里分不出）。对"与已连通区相邻且紧贴权威格"
     的阻塞格取瓦片号，做成按 tileset 的白名单（同 `_WALK_OVER_TILES` 机制，但数据驱动）。
     ⚠ 安全阀：单个 (tileset, 瓦片) 在全游戏放开 > `CAP` 格就丢弃（防把普通墙当闸门）。

实测（1146 门 / 1022 宝箱，经门口径）：
  · 原始                                  门不可达 160   宝箱 815/1022 = 79.7%
  · (A) 空瓦片豁免                         门不可达  72   宝箱 897/1022 = 87.8%
  · (A)+(B) 闸门白名单                     门不可达  72   宝箱 **974/1022 = 95.3%**
    代价：全游戏新增可走格 2909 / ~78 万 = 0.37%
用法：`python tools/calibrate_void_tiles.py`（改地图/宝箱/通行规则后重跑）
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import real_map as realm          # noqa: E402
from core import world_graph as wg          # noqa: E402
from core.real_map import flag_walkable     # noqa: E402

ASSETS = ROOT / "assets"
MAPS = ASSETS / "maps"
OUT = ASSETS / "void_tiles.json"
CAP = 200          # 单个 (tileset, 瓦片) 允许放开的格数上限


def _flood(m, seeds, tr):
    seen, q = set(), deque()
    for s in seeds:
        if s not in seen and (m.passable(*s) or s in tr):
            seen.add(s); q.append(s)
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if (nx, ny) in seen or not m.in_bounds(nx, ny):
                continue
            if m.passable(nx, ny) or (nx, ny) in tr:
                seen.add((nx, ny)); q.append((nx, ny))
    return seen


def main() -> int:
    # ⚠ 自举: 必须用**原始启发式**算证据 —— 否则 RealMap 加载时会先应用上一版 void_tiles.json
    #   的豁免, 那些瓦片已不在 _void/_black 里, 证据全被吃掉 (exempt 变 0)。
    realm._VOID_EXEMPT = {}          # 空 dict = 不豁免 (不会触发重新读文件)

    chests = json.loads((ASSETS / "chests.json").read_text(encoding="utf-8"))["maps"]
    refs: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    for p in MAPS.glob("*.map"):
        base = p.stem
        for (x, y) in wg.transitions(base):
            refs[base].append((x, y, "door"))
        sp = wg.spawn(base)
        if sp:
            refs[base].append((sp[0], sp[1], "spawn"))
    for base, lst in chests.items():
        for c in lst:
            refs[base].append((int(c["x"]), int(c["y"]), "chest"))

    # ---- 装载 + 第 1 遍: 空瓦片证据 ----
    maps: dict[str, "realm.RealMap"] = {}
    evidence: dict[str, Counter] = defaultdict(Counter)
    for base, lst in refs.items():
        try:
            m = realm.load(base)
        except Exception:
            continue
        maps[base] = m
        for (px, py) in m.pcpos:
            lst.append((px, py, "pcpos"))
        ts = m.ts_name
        for (x, y, kind) in lst:
            if not (0 <= x < m.w and 0 <= y < m.h):
                continue
            idx = m.tile_index(x, y)
            if idx in m._void or idx in m._black:
                evidence[ts][f"{idx}:{kind}"] += 1

    exempt: dict[str, list[int]] = {}
    detail: dict[str, dict[str, int]] = {}
    for ts, cnt in evidence.items():
        per_tile: dict[int, Counter] = defaultdict(Counter)
        for key, n in cnt.items():
            i, kind = key.split(":")
            per_tile[int(i)][kind] += n
        keep, info = [], {}
        for idx, kinds in sorted(per_tile.items()):
            if kinds["door"] + kinds["spawn"] + kinds["pcpos"] >= 1 or kinds["chest"] >= 1:
                keep.append(idx)
                info[str(idx)] = dict(kinds)
        if keep:
            exempt[ts] = keep
            detail[ts] = info

    # ---- 第 2 遍: 闸门瓦片 (用豁免后的通行状态算连通) ----
    gate: dict[str, Counter] = defaultdict(Counter)
    for base, m in maps.items():
        e = exempt.get(m.ts_name)
        if e:
            m._void = m._void - set(e)
            m._black = m._black - set(e)
        tr = wg.transitions(base)
        seen = _flood(m, list(tr) or [m.start_pos()], tr)
        for (x, y, kind) in refs.get(base, ()):
            if not (0 <= x < m.w and 0 <= y < m.h):
                continue
            nb = [p for p in ((x, y), (x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
                  if m.in_bounds(*p)]
            if any(p in seen for p in nb):
                continue
            gates = set()
            for p in nb:
                if m.passable(*p) or p in tr:
                    continue
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    if (p[0] + dx, p[1] + dy) in seen:
                        gates.add(p)
                        break
            for g in gates:
                gate[m.ts_name][m.tile_index(*g)] += 1

    # 安全阀: 统计每个 (tileset, tile) 放开多少格, 超过 CAP 的丢掉
    opened: Counter = Counter()
    for base, m in maps.items():
        wo = set(gate.get(m.ts_name, ()))
        if not wo:
            continue
        for y in range(m.h):
            for x in range(m.w):
                idx = m.tile_index(x, y)
                if idx in wo and not m.passable(x, y):
                    opened[(m.ts_name, idx)] += 1
    walk_over: dict[str, list[int]] = {}
    dropped = []
    for ts, cnt in gate.items():
        keep = sorted(t for t in cnt if opened.get((ts, t), 0) <= CAP)
        dropped += [(ts, t, opened.get((ts, t), 0)) for t in cnt if t not in keep]
        if keep:
            walk_over[ts] = keep

    OUT.write_text(json.dumps({
        "note": "空瓦片豁免 + 闸门瓦片白名单 (由 tools/calibrate_void_tiles.py 生成; "
                "证据=原版 door/spawn/pcpos/权威宝箱表)",
        "cap": CAP,
        "exempt": exempt,
        "walk_over": walk_over,
        "evidence": detail,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"扫描 {len(maps)} 张图")
    print(f"  exempt   : {len(exempt)} 图集 / {sum(len(v) for v in exempt.values())} 瓦片")
    print(f"  walk_over: {len(walk_over)} 图集 / {sum(len(v) for v in walk_over.values())} 瓦片"
          f"  (放开 {sum(opened[k] for ts, v in walk_over.items() for k in [(ts, t) for t in v])} 格)")
    if dropped:
        print(f"  安全阀丢弃 {len(dropped)} 个超大开口瓦片: {dropped[:5]}")
    print(f"-> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
