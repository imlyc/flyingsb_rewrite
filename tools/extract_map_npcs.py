"""从 assets/maps/*.mfo 提取「地图 → 角色(NPC/传送点)」表 (A: FC 放置数据).

.mfo 注释自带字段名:
    //              x   y  z  d  act  link
    pcpos <i> =    10, 9, 0, 0, 0,   0
    //              m  pp key act c0  c1  o0  o1
    jmp   <i> =    22, 0, 0,  0, -1, -1, -1, -1

**核心结论: 某个位置 ID 同时充当「传送目标」与「剧本表索引」**
  · `pcpos[i]` = 地图上的一个"角色/入口"(x, y, 朝向 d), `link` → `jmp[link]`;
  · `jmp.m` = 与该位置关联的 ID。这个 ID 有**双重身份**:
      - 它是**目标位置 ID** (传送点) —— 1136 条 jmp 里 982 条的 m 是现存地图 ID;
      - 它同时是 **assets/script/script_table.json 的索引** —— 1087 条里 1014 条能解出真实对白。
    两者不是巧合: 原版**位置表与剧本表共用同一套 ID 空间** (0..668),
    所以"走到某处 → 去位置 m → 播放 script[m]"是一条统一链路。
  · `jmp.act`: 0/1 ≈ 纯传送点, >=2 ≈ 站立角色; 但从数据看它更像精灵/动画类型,
    不宜当作硬分类 (TAL0___P 全为 2 但仍是通往各房间的入口)。`jmp.c0/o0` = 精灵帧号。

实证样本 (m 解出的对白与地图主题完全吻合):
  · TAS0___P: m=18「这里是*五指村*, 是位于世界最南方的村庄」、19 五行山妖怪、20 神像被破坏、21 供奉猴子;
  · TAL0___P: m=353「这里是*阿尔夏*, 是北洲唯一的港口」、351「我是负责酒店的」、130「您不能从这儿通过」;
  · T_LOC0_P (南南部洲世界地图): m=22 指路村民、30 饰品情报;
  · TFI0___P (다섯손가락마을 = 五指村): m=23..28 神像/村民相关。

**角色图形来自地图瓦片 (已实证)**:
  · 每个 pcpos 落点所在的地图可视瓦片都是**稀有瓦片** (整图只在各 pcpos 处出现), 且
    `瓦片号 == jmp.c0 + 20` (TAS0 312↔292 / TFI0 69↔49) → 原版把角色/门的图形**烘焙进地图**;
  · `jmp.c0 >= 0` 的只有 27 条 (指额外叠一张 FC 精灵)。
  · `kind` 字段是**弱启发式** (按 `m` 是否在 location_map 的现存地图 ID 里区分
    entrance/npc); 因位置表与剧本表共用 ID 空间, **不完全可靠**, 仅供统计参考, 渲染不依赖它。

产物: assets/map_npcs.json
  {"maps": {base: {"name","id",
                   "npcs":[{x,y,d,act,script,sprite,kind,text}],   # 全部 pcpos 条目
                   "doors":[{x,y,target}]}},
   "stats": {...}}
  kind: "door"(纯传送) / "entrance"(带对白的入口) / "npc"(真角色)
跑法: cd rewrite && venv/Scripts/python -m tools.extract_map_npcs
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAPS = ROOT / "assets" / "maps"
TABLE = ROOT / "assets" / "script" / "script_table.json"
OUT = ROOT / "assets" / "map_npcs.json"

NAME_RE = re.compile(r'mapname\s*=\s*"([^"]*)"')
PCPOS_RE = re.compile(r"pcpos\s+\d+\s*=\s*([^\n/]+)")
JMP_RE = re.compile(r"jmp\s+\d+\s*=\s*([^\n/]+)")


def decode(raw: bytes) -> str:
    for enc in ("cp949", "euc-kr", "big5", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp949", "replace")


def _ints(s: str, n: int) -> list[int | None]:
    out: list[int | None] = []
    for tok in s.split(","):
        tok = tok.strip()
        m = re.match(r"^(-?\d+)", tok)          # 容忍 "0y" 这类脏 token
        out.append(int(m.group(1)) if m else None)
    while len(out) < n:
        out.append(None)
    return out[:n]


def parse(base: str, loc_ids: set[int]) -> dict:
    t = decode((MAPS / f"{base}.mfo").read_bytes())
    nm = NAME_RE.search(t)
    name = nm.group(1).strip() if nm else ""
    jmps = [_ints(s, 8) for s in JMP_RE.findall(t)]

    npcs, doors = [], []
    for rec in PCPOS_RE.findall(t):
        v = _ints(rec, 6)                        # x y z d act link
        if v[0] is None or v[1] is None or v[5] is None:
            continue
        link = v[5]
        if not (0 <= link < len(jmps)):
            continue
        j = jmps[link]
        m, jact = j[0], j[3]
        if m is None:
            continue
        if jact == 0 or jact is None:            # 纯传送点
            doors.append({"x": v[0], "y": v[1], "d": v[3], "target": m,
                          "kind": "door"})
        else:
            # m 是现存地图 ID → 房间/地图入口; 否则是真剧本角色 (FC)
            kind = "entrance" if m in loc_ids else "npc"
            npcs.append({"x": v[0], "y": v[1], "d": v[3], "act": jact,
                         "script": m, "sprite": [j[4], j[6]], "kind": kind})

    return {"name": name or None,
            "id": int(name) if name.isdigit() else None,
            "npcs": npcs, "doors": doors}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    files = sorted(p.stem for p in MAPS.glob("*.mfo"))
    if not files:
        print(f"[skip] 没有 .mfo: {MAPS}")
        return 1
    table = {}
    if TABLE.exists():
        table = {e["id"]: e for e in json.loads(TABLE.read_text("utf-8"))}
    loc_ids: set[int] = set()
    LOC = ROOT / "assets" / "location_map.json"
    if LOC.exists():
        loc_ids = {int(k) for k in json.loads(LOC.read_text("utf-8")).get("by_id", {})}

    out, n_npc, n_door, n_real = {}, 0, 0, 0
    n_entrance = 0
    for base in files:
        d = parse(base, loc_ids)
        out[base] = d
        for npc in d["npcs"]:
            n_npc += 1
            if npc.get("kind") == "entrance":
                n_entrance += 1
            e = table.get(npc["script"])
            if e and not e.get("default") and e.get("text"):
                n_real += 1
                npc["text"] = (e.get("s") or e["text"])[:60]
        n_door += len(d["doors"])

    OUT.write_text(json.dumps(
        {"maps": out, "stats": {"npcs": n_npc, "doors": n_door,
                                "npcs_with_dialogue": n_real,
                                "entrances": n_entrance,
                                "real_npcs": n_npc - n_entrance}},
        ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"地图 {len(out)} 张 → {OUT.relative_to(ROOT)}")
    print(f"  条目 {n_npc} 个: 入口 {n_entrance} / 真角色 {n_npc - n_entrance} "
          f"(有对白 {n_real}) / 纯传送点 {n_door}")
    for b in ("TAS0___P", "TAL0___P", "T_LOC0_P"):
        d = out.get(b)
        if not d:
            continue
        print(f"  [{b}] {d['name']}  NPC {len(d['npcs'])} 传送 {len(d['doors'])}")
        for npc in d["npcs"][:4]:
            print(f"     ({npc['x']:>3},{npc['y']:>3}) act={npc['act']} "
                  f"script={npc['script']:<4d} {npc.get('text', '')[:34]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
