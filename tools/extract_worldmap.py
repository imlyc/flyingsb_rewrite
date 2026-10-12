"""提取原版世界地图 (M 键) 地点表 → assets/worldmap_locations.json

来源: FlyingSB.exe 数据段 0x14b41c 起, 44 个条目, 步长 0x54 (84 字节)。
条目结构 (u32 索引, 部分字段语义已实证):
  +12 = x, +16 = y          ← LMAP00 (2000x1600) 上的标记坐标
  +32 = Big5 名称串 VA      ← 已实证 (五指村/雅士蘭/阿爾夏...)
  +36 = 位置 ID             ← 与 location_map.json 的 by_id 同一 ID 空间
                               (五指村=22, 阿爾夏=348 与已知枢纽吻合)
  其余原始 DWORD 原样保留 (labels: w0..w11, w40..w80), 语义待考。

跑法: cd rewrite && venv/Scripts/python.exe -m tools.extract_worldmap
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

import pefile

ROOT = Path(__file__).resolve().parent.parent
ORIGIN = Path(__file__).resolve().parents[2] / "origin" / "flyingsb"
OUT = ROOT / "assets" / "worldmap_locations.json"

ENTRY_STRIDE = 0x54
FIRST_ENTRY_OFF = 0x14B41C          # 五指村条目
N_ENTRIES = 44
IMAGE_BASE = 0x400000


def main() -> None:
    exe_path = ORIGIN / "FlyingSB.exe"
    data = exe_path.read_bytes()
    pe = pefile.PE(name=str(exe_path), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase

    def va2off(va: int) -> int | None:
        rva = va - base
        for s in pe.sections:
            if s.VirtualAddress <= rva < s.VirtualAddress + s.Misc_VirtualSize:
                return s.PointerToRawData + (rva - s.VirtualAddress)
        return None

    by_id: dict[str, str] = {}
    lmap = ROOT / "assets" / "location_map.json"
    if lmap.exists():
        by_id = json.loads(lmap.read_text(encoding="utf-8")).get("by_id", {})

    try:
        from opencc import OpenCC
        cc = OpenCC("t2s")
    except Exception:
        cc = None

    entries = []
    for i in range(N_ENTRIES):
        off = FIRST_ENTRY_OFF + i * ENTRY_STRIDE
        words = struct.unpack_from("<21I", data, off)
        x, y = words[3], words[4]
        name_va = words[8]
        loc_id = words[9]
        name = ""
        if name_va:
            o = va2off(name_va)
            if o is not None:
                end = data.find(b"\0", o)
                try:
                    name = data[o:end].decode("big5")
                except Exception:
                    name = ""
        name_s = cc.convert(name) if (cc and name) else name
        wid = str(loc_id)
        entries.append({
            "name": name,            # 原版 Big5 繁体
            "name_s": name_s,        # 简体 (opencc)
            "id": loc_id,            # 位置 ID (= location_map.json by_id)
            "base": by_id.get(wid),  # 对应地图资源名 (可能为 None)
            "x": x, "y": y,          # LMAP00 像素坐标
            "raw": [f"0x{w:08x}" for w in words],
        })

    out = {
        "source": f"FlyingSB.exe @ 0x{FIRST_ENTRY_OFF:x}, stride 0x{ENTRY_STRIDE:x}",
        "image": "assets/ui/LMAP00.bmp (2000x1600)",
        "count": len(entries),
        "locations": entries,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已写出 {OUT} ({len(entries)} 条)")
    no_base = [e["name"] for e in entries if not e["base"]]
    print(f"无对应地图资源的地点: {no_base}")


if __name__ == "__main__":
    main()
