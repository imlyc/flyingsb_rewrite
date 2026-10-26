"""从 FlyingSB.exe 导出 ps_ 网格图集登记表 @0x5B0008 (52B/记录: [16B 文件名][cols rows anchor_x anchor_y i16]...)
→ core/grid_atlas_table.py 的 GRID_ATLAS (全部 1302 项里有文件名的).
跑法: cd rewrite && venv/bin/python -m tools.extract_grid_atlas
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

from tools.extract_normal_attacks import EXE, Exe

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "core" / "grid_atlas_table.py"
BASE, REC, COUNT = 0x5B0008, 52, 1302


def main() -> None:
    e = Exe(EXE)
    o = e.off(BASE)
    rows = []
    for i in range(COUNT):
        r = e.d[o + i * REC:o + i * REC + REC]
        nm = r[:16].split(b"\0")[0].decode("latin1").strip()
        if not nm.startswith("!"):
            continue
        cols, nrows, ax, ay = struct.unpack_from("<4h", r, 16)
        key = "ps_" + nm[1:].split(".")[0].upper()
        rows.append(f'    {i}: ("{key}", {cols}, {nrows}, {ax}, {ay}),')
    src = OUT.read_text(encoding="utf-8")
    head = src[:src.index("GRID_ATLAS: dict")]
    tail = src[src.index("\n}\n", src.index("GRID_ATLAS: dict")) + 3:]
    body = "GRID_ATLAS: dict[int, tuple[str, int, int, int, int]] = {\n" + "\n".join(rows) + "\n}\n"
    head = re.sub(r"\(2026-10-20\)", "(2026-10-20; 2026-10-26 tools/extract_grid_atlas.py 全量重导)", head)
    OUT.write_text(head + body + tail, encoding="utf-8")
    print("written", OUT, len(rows), "atlases")


if __name__ == "__main__":
    main()
