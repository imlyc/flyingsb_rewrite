"""自动生成 assets/chests.json 骨架 (待 exe/攻略校准内容).

判定: .map 尾部 object 层里「独立物体格」(object type ∈ {3,7,11,13,15,19,23}, tail_b==1,
实例 idx!=0) 中「可通行」的子集 = 候选宝箱 (宝箱一般可踩上去/面前交互).

内容: 暂用轮转占位物品, 方便先跑通开箱流程; 之后用 exe 提取的真实表或攻略覆盖 item_id.
跑法: cd rewrite && venv/Scripts/python -m tools.gen_chests
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

from core.real_map import load

ROOT = Path(__file__).resolve().parent.parent
MAPS = ROOT / "assets" / "maps"
OUT = ROOT / "assets" / "chests.json"

OBJ_TYPES = {3, 7, 11, 13, 15, 19, 23}
# 占位物品池 (覆盖装备/消耗, 开箱先有反馈); 真实内容待填
PLACEHOLDER_POOL = [299, 300, 305, 124, 128, 1, 65, 201, 203, 311]


def main() -> int:
    result: dict[str, list[dict]] = {"maps": {}}
    pool_i = 0
    for p in sorted(MAPS.glob("*.map")):
        base = p.stem
        data = p.read_bytes()
        if len(data) < 480:
            continue
        u = struct.unpack("<120I", data[:480])
        w, h = u[6], u[7]
        cells = w * h
        off = (120 + 2 * cells) * 4
        if len(data) - off < cells * 8:
            continue
        try:
            rm = load(base)
        except Exception:
            continue
        chests: list[dict] = []
        for i in range(cells):
            a, b = struct.unpack_from("<II", data, off + i * 8)
            if (a >> 16) in OBJ_TYPES and b == 1 and (a & 0xFFFF) != 0:
                x, y = i % w, i // w
                if not rm.passable(x, y):
                    continue
                item_id = PLACEHOLDER_POOL[pool_i % len(PLACEHOLDER_POOL)]
                pool_i += 1
                chests.append({
                    "x": x, "y": y, "item_id": item_id, "qty": 1,
                    "note": f"TODO: 待 exe/攻略校准 (objtype={a >> 16}, idx={a & 0xFFFF})",
                })
        if chests:
            result["maps"][base] = chests

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(len(v) for v in result["maps"].values())
    print(f"生成 {len(result['maps'])} 张地图, 共 {total} 个候选宝箱 → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
