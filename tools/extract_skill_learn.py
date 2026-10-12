"""从 FlyingSB.exe 提取「角色 → 等级 → 技能」学习表 (静态逆向, ImageBase 0x400000).

逆向出的结构:
  · 学习表 VA **0x64216C**, 每个角色记录 **0x50 (80) 字节** = **10 组 [等级, 技能下标]**
    (每组 8 字节, 等级 <= 0 表示到此为止), 共 16 条记录 (与角色定义表 0x689D64 同序);
  · 访问函数 `0x49ccf2(charIdx, newLevel)`: 遍历该角色的 10 组, 若 `等级 == newLevel`
    则学会该技能并把「已学」写入角色结构, 返回技能 id; 否则返回 -1;
  · **技能下标是该角色技能池内的下标** (池见 `core.skills.CHARACTER_SKILL_POOL`,
    即连续 id 区间; 如孙悟空 0..9 / 美娜 10..19 / …), 故实际技能 id = 池[下标];
  · **未在表里出现的池下标 = 开局就会** (例: 美娜表为 下标1..8, 则她开局带 小回复/召唤精灵)。

实测 (lv -> 技能):
  孙悟空: 2,4,6,9,12,16,20,25,31,38
  美娜:   (开局:小回复/召唤精灵) 4,7,11,15,20,25,31,37
  三藏法师: 2,9,17,26,36    猪八戒: 5,10,18,27,37    沙悟净: (无, 开局全带)
  蒙面人: 2,8,16,26,38      乐神杰特: 2,3,5,8,11,15,19,24,30,36
  破无: 5,12,20,26,36       捕山: 5,12,20,28,38       紫河: 9,14,19,22,25,28,31,35,40

产物: assets/skill_learn.json
  {"records": {"<recIdx>": {"name": 繁体名, "learn": [[level, poolIdx], ...]}}}
跑法: cd rewrite && venv/Scripts/python -m tools.extract_skill_learn
"""

from __future__ import annotations

import json
import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = Path(os.environ.get(
    "FLYINGSB_EXE", ROOT.parent / "origin" / "flyingsb" / "FlyingSB.exe"))
OUT = ROOT / "assets" / "skill_learn.json"
CHARS = ROOT / "assets" / "characters_table.json"

IMG = 0x400000
BASE, STRIDE, N_CHAR, N_SLOT = 0x64216C, 0x50, 16, 10


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not EXE.exists():
        print(f"[skip] 找不到 exe: {EXE}")
        return 1
    raw = EXE.read_bytes()

    names: list[str] = []
    if CHARS.exists():
        names = [c["name"] for c in json.loads(
            CHARS.read_text(encoding="utf-8"))["characters"]]

    sys.path.insert(0, str(ROOT))
    from core.skills import CHARACTER_SKILL_POOL

    records: dict[str, dict] = {}
    total = 0
    for c in range(N_CHAR):
        learn: list[list[int]] = []
        for i in range(N_SLOT):
            lv, idx = struct.unpack_from("<II", raw, BASE - IMG + c * STRIDE + i * 8)
            if lv == 0xFFFFFFFF or lv <= 0:
                break
            learn.append([int(lv), int(idx)])
        if learn:
            total += len(learn)
        records[str(c)] = {
            "name": names[c] if c < len(names) else "",
            "learn": learn,
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"records": records}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"学习表 {N_CHAR} 条 / {total} 条学习项 → {OUT.relative_to(ROOT)}")
    for c in (1, 3, 4, 6, 12):
        r = records[str(c)]
        pool = CHARACTER_SKILL_POOL.get(r["name"]) or []
        desc = ", ".join(
            f"L{lv}→{pool[idx] if idx < len(pool) else f'?{idx}'}" for lv, idx in r["learn"])
        print(f"  [{c}] {r['name']}: {desc or '(无)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
