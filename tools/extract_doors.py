"""从 FlyingSB.exe 读「门/机关」表 → assets/door_table.json.

逆向 (FUN_005324ce, 事件脚本 e2.00 [id, 开关]): 表在 VA 0x686358, 每项 0x24 字节, 共 0x199 项:
  +0x00 u32 地图 id (地图表下标)   +0x04 x   +0x08 y   +0x0C ?   +0x10 宽(格)   +0x14 高(格)
  +0x18 ptr 开 (state 1) 的格数据   +0x1C ptr 关 (state 0) 的格数据
格数据: 宽×高 个格, 每格 4 dword = [层0 瓦片, 层0 属性, 层1 瓦片, 层1 属性] (与 .map 两层同格式),
FUN_004b82f4 把它们直接写进当前地图 (DAT_008451a8 瓦片 / DAT_008491a8 属性) 并重算通行 cell.
开关状态存位图 DAT_0086ad6c (随存档). 载图时 FUN_0053262a 按位图重放.

跑法: cd rewrite && venv/bin/python -m tools.extract_doors
"""
from __future__ import annotations

import json
import os
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORIGIN = Path(os.environ.get("FLYINGSB_ORIGIN", ROOT.parent / "origin" / "flyingsb"))
EXE = Path(os.environ.get("FLYINGSB_EXE", ORIGIN / "FlyingSB.exe"))
OUT = ROOT / "assets" / "door_table.json"

TABLE_VA, STRIDE, COUNT, IMAGE_BASE = 0x686358, 0x24, 0x199, 0x400000


def parse(exe: Path = EXE) -> list[dict]:
    data = exe.read_bytes()
    u32 = lambda va: struct.unpack_from("<I", data, va - IMAGE_BASE)[0]
    out = []
    for i in range(COUNT):
        e = TABLE_VA + i * STRIDE
        mp, x, y, p3, w, h, p_open, p_closed = (u32(e + k) for k in range(0, 0x20, 4))
        if mp == 0 and w == 0 and h == 0:
            continue
        def cells(ptr: int) -> list[list[int]]:
            if not (IMAGE_BASE < ptr < IMAGE_BASE + len(data)):
                return []
            n = w * h
            vals = struct.unpack_from(f"<{4 * n}I", data, ptr - IMAGE_BASE)
            return [list(vals[4 * k: 4 * k + 4]) for k in range(n)]
        out.append({"id": i, "map": mp, "x": x, "y": y, "p3": p3, "w": w, "h": h,
                    "open": cells(p_open), "closed": cells(p_closed)})
    return out


def main() -> int:
    rows = parse()
    OUT.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    print(f"门表 → {OUT}: {len(rows)} 项")
    for r in rows[:3] + [r for r in rows if r["id"] == 405]:
        print(f"  id {r['id']} map {r['map']} ({r['x']},{r['y']}) {r['w']}x{r['h']} open={r['open'][:2]} closed={r['closed'][:2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
