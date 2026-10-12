"""解析 assets/maps/*.mfo → 位置表 (地图切换骨架用).

规则 (TAL0___P / TAS0___P 实证):
  · mapname 为数字 = 该地图的**位置 ID** (48..487); 为文字则为"命名位置"(镇子/世界地图, 韩文)
  · pcpos[i] = (x, y, z, d, act, link)   d=0 一般是出生点; link = jmp 下标
  · jmp[k]   = (m, pp, key, act, c0, c1, o0, o1)   m = 目标位置 ID
  · **站在 pcpos[i] 的 (x,y) 上 → 触发 jmp[pcpos[i].link] → 传送到 m**
  · jmp 的 c0/c1/o0/o1 是目标端坐标区 (单位未定, 暂存)

输出: assets/location_map.json
  {"by_id": {id: {...}}, "by_base": {base: id}, "named": {base: name}}
  每条 {...} = {base, id, name, spawn:[x,y], transitions:[[x,y,target], ...]}

跑法: cd rewrite && venv/Scripts/python -m tools.extract_locations
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAPS = ROOT / "assets" / "maps"
OUT = ROOT / "assets" / "location_map.json"

NAME_RE = re.compile(r'mapname\s*=\s*"([^"]*)"')

# "小 ID 空间" 0..47 = 命名地图 (世界地图/城镇); 由 .mfo 的 jmp 邻接结构 + 资源分组推得:
#   0..9   T_LOC0..9_P (世界地图段)
#   10..21 아스람 (hub TAS0___P=10, 店铺 TAS0_00P..TAS0_10P=11..21; 店铺都跳回 10)
#   22..29 다섯손가락마을 (hub TFI0___P=22, 房间 TFI0_00P..06P=23..29)
#   30..47 오행산 (TOH0_* 18 张, 相邻互跳链)
_SMALL_ID: dict[str, int] = {}
for _i in range(10):
    _SMALL_ID[f"T_LOC{_i}_P"] = _i
_SMALL_ID["TAS0___P"] = 10
for _i in range(11):
    _SMALL_ID[f"TAS0_{_i:02d}P"] = 11 + _i
_SMALL_ID["TFI0___P"] = 22
for _i in range(7):
    _SMALL_ID[f"TFI0_{_i:02d}P"] = 23 + _i
for _i, _suf in enumerate(["00", "01", "03", "04", "05", "06", "07", "08", "09",
                           "11", "12", "13", "14", "15", "16", "17", "18", "19"]):
    _SMALL_ID[f"TOH0_{_suf}P"] = 30 + _i

# 城镇/房间类地名标记: 这类地图不遇敌 (即使 .mfo 带 enemytype)
SAFE_MARKERS = ("마을", "ROOM", "INN", "PUB", "ITEM", "WEP", "ACC", "슬럼", "아스람", "여관")
PCPOS_RE = re.compile(r"pcpos\s+\d+\s*=\s*([-\d,\s]+)")
JMP_RE = re.compile(r"jmp\s+\d+\s*=\s*(-?\d+)")


def decode(raw: bytes) -> str:
    for enc in ("cp949", "euc-kr", "big5", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp949", "replace")


def parse(base: str) -> dict:
    t = decode((MAPS / f"{base}.mfo").read_bytes())
    m = NAME_RE.search(t)
    name = m.group(1).strip() if m else ""
    lid = int(name) if name.isdigit() else _SMALL_ID.get(base)

    pcpos = []
    for rec in PCPOS_RE.findall(t):
        v = [x.strip() for x in rec.split(",") if x.strip()]
        if len(v) >= 6 and v[0].lstrip("-").isdigit():
            pcpos.append([int(v[0]), int(v[1]), int(v[3]), int(v[5])])  # x, y, d, link
    jmp = [int(x) for x in JMP_RE.findall(t)]

    spawn = None
    for x, y, d, _link in pcpos:
        if d == 0:
            spawn = [x, y]
            break
    if spawn is None and pcpos:
        spawn = [pcpos[0][0], pcpos[0][1]]

    transitions = []
    for x, y, _d, link in pcpos:
        if 0 <= link < len(jmp):
            transitions.append([x, y, jmp[link]])
    has_et = "enemytype" in t
    safe = any(k in name for k in SAFE_MARKERS)
    return {"base": base, "id": lid, "name": name or None,
            "spawn": spawn, "transitions": transitions,
            "enc": has_et and not safe}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    files = sorted(p.stem for p in MAPS.glob("*.mfo"))
    if not files:
        print(f"[skip] 没有 .mfo: {MAPS}")
        return 1
    locations: dict[str, dict] = {}
    by_id: dict[str, str] = {}
    n_tr = 0
    for base in files:
        loc = parse(base)
        n_tr += len(loc["transitions"])
        locations[base] = loc
        if loc["id"] is not None:
            by_id[str(loc["id"])] = base
    OUT.write_text(json.dumps({"locations": locations, "by_id": by_id},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    named = sum(1 for v in locations.values() if v["id"] is None and v["name"])
    print(f"位置表 → {OUT.relative_to(ROOT)}")
    print(f"  数字ID位置 {len(by_id)} 个 / 命名位置 {named} 个 / 传送点 {n_tr} 条")
    sample = locations.get("TAL0___P")
    if sample:
        print(f"  例 [TAL0___P id=348]: spawn={sample['spawn']} "
              f"transitions={sample['transitions'][:5]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
