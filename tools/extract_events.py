"""解析 assets/maps/*.mfo → 结构化地图事件表.

.mfo 是文本 (Big5) 的地图事件配置, 注释里自带字段名:

  mapname = "<地点名>"
  camera_range_check = true
  //                x  y  z  d  act  link
  pcpos   <i> =   10, 9, 0, 0, 0, 0        # 角色/NPC 站位 (x,y,z,朝向,动作,链接)
  //                m  pp key act c0 c1 o0 o1
  jmp     <i> =   22, 0, 0, 0, -1, -1, -1, -1   # 跳转/传送 (目标地图, ...)
  anime   <i> =   0, 2, -1, 6, 20, 30     # 动画/循环帧
  scroll  <i> =   ...
  player = auto | enemy = auto | enemytype = 141,147,...   # 战斗配置
  battlearea = auto | partylevel = 100 | escape = no
  [ battleset <i> ] ... [ battleset end ]

输出: assets/maps_events.json  { "<地图名>": {..., "pcpos":[...], "jmp":[...]} }

跑法: cd rewrite && venv/Scripts/python -m tools.extract_events
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAPS = ROOT / "assets" / "maps"
OUT = ROOT / "assets" / "maps_events.json"

KEYVAL = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(\d*)\s*=\s*(.*?)\s*(?://.*)?$")
INTS = re.compile(r"-?\d+")


def decode(raw: bytes) -> str:
    for enc in ("cp949", "euc-kr", "big5", "gbk"):   # .mfo 注释/地名是原版韩文
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("big5", "replace")


def parse_mfo(path: Path) -> dict:
    out: dict = {}
    text = decode(path.read_bytes())
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("//"):
            continue
        if s.startswith("["):
            continue
        m = KEYVAL.match(s)
        if not m:
            continue
        key, idx, val = m.group(1).lower(), m.group(2), m.group(3).strip()
        if key == "mapname":
            out["mapname"] = val.strip('"').strip()
        elif key in ("pcpos", "jmp", "anime", "scroll"):
            toks = [t.strip() for t in val.split(",")]
            rec = {"raw": toks}
            if key == "jmp":
                rec.update(zip(("m", "pp", "key", "act", "c0", "c1", "o0", "o1"), toks))
            elif key == "pcpos":
                rec.update(zip(("x", "y", "z", "d", "act", "link"),
                               [int(t) if t.lstrip("-").isdigit() else t for t in toks]))
            else:
                rec["vals"] = [int(t) for t in INTS.findall(val)]
            out.setdefault(key, []).append(rec)
        else:
            nums = [int(t) for t in INTS.findall(val)]
            out.setdefault(key, nums if nums else val)
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    files = sorted(MAPS.glob("*.mfo"))
    if not files:
        print(f"[skip] 没有 .mfo (先跑 tools.extract_dll): {MAPS}")
        return 1
    result: dict[str, dict] = {}
    for p in files:
        result[p.stem] = parse_mfo(p)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    # 地图关联图: 位置ID → 地图文件 + jmp 目标ID (mapname 数字 = 位置ID, jmp.m = 目标ID)
    graph: dict[str, dict] = {}
    for base, ev in result.items():
        mn = str(ev.get("mapname", "")).strip()
        lid = int(mn) if mn.isdigit() else None
        tgts = []
        for r in ev.get("jmp", []):
            v = r.get("m")
            if isinstance(v, str) and v.lstrip("-").isdigit():
                tgts.append(int(v))
        if lid is not None:
            graph[str(lid)] = {"map": base, "jmp": tgts, "name": None}
    graph_path = ROOT / "assets" / "map_graph.json"
    graph_path.write_text(json.dumps(graph, ensure_ascii=False, indent=1), encoding="utf-8")
    ids = sorted(int(k) for k in graph)
    print(f"  关联图 → {graph_path.name}: {len(graph)} 个位置ID"
          + (f" ({ids[0]}..{ids[-1]})" if ids else ""))
    n_jmp = sum(len(v.get("jmp", [])) for v in result.values())
    n_pc = sum(len(v.get("pcpos", [])) for v in result.values())
    n_battle = sum(1 for v in result.values() if "enemytype" in v)
    print(f"解析 {len(files)} 个 .mfo → {OUT.relative_to(ROOT)}")
    print(f"  pcpos {n_pc} 条 / jmp {n_jmp} 条 / 带战斗配置 {n_battle} 张")
    sample = next(iter(result))
    print(f"  例 [{sample}]: " + json.dumps(result[sample], ensure_ascii=False)[:220])
    return 0


if __name__ == "__main__":
    sys.exit(main())
