"""扫描原版 exe/dll, 寻找宝箱/地图/物品相关表.

由于 mapset.dll 里的 .map 尾部已确认是 object/event 层, 宝箱表很可能在 exe 里
(物品内容/对象属性) 或 .map tail(对象实例). 本工具做第一轮快速扫描:
  - 搜地图名字符串 (TFI0/TAS0/TOH0 等)
  - 搜已知物品 id (u16/u32)
  - 搜 "宝箱/Chest/상자" 等多语言关键字
  - 输出前 50 条命中及上下文

用法:
    cd rewrite && venv/Scripts/python -m tools.reverse_exe_chests
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORIGIN = ROOT.parent / "origin" / "flyingsb"
TARGETS = ["FlyingSB.exe", "MAPSET.dll", "PCXSET.dll"]

# 已知物品 id (恢复药/良药/优药/如意棒/双截棍/草帽/薄衣等)
ITEM_IDS = [1, 65, 124, 128, 196, 299, 300, 301, 305]

# 多语言宝箱/事件关键字
KEYWORDS = [
    b"\xb1\xe8\xbb\xdd",        # 韩文 "宝箱" 在 CP949 中可能是 
    b"Chest", b"chest", b"Box", b"box",
    b"\xe5\xae\x9d\xe7\xae\xb1",  # 中文 GB "宝箱"
    b"ITEM", b"item",
]

# 地图名前缀
MAP_PREFIXES = [b"TFI0", b"TAS0", b"TOH0", b"TOR0", b"TKA0", b"TDS3",
                b"TGE0", b"TMY0", b"TDI0", b"TAL0", b"TMO0", b"TMT10",
                b"TMA0", b"T_LOC0", b"TARA", b"TARB"]


def _ctx(data: bytes, pos: int, radius: int = 16) -> str:
    start = max(0, pos - radius)
    end = min(len(data), pos + radius)
    chunk = data[start:end]
    return chunk.hex(" ") + " | " + repr(chunk)


def scan(name: str, data: bytes) -> None:
    print(f"\n=== {name} ({len(data)} bytes) ===")
    hits = 0

    # 1) 地图名
    for prefix in MAP_PREFIXES:
        for m in re.finditer(re.escape(prefix), data):
            if hits >= 50:
                break
            print(f"  map_str @ 0x{m.start():06X}: {_ctx(data, m.start(), 12)}")
            hits += 1
        if hits >= 50:
            break

    # 2) 物品 id (u16/u32 little-endian)
    for iid in ITEM_IDS:
        for width, fmt in ((2, "<H"), (4, "<I")):
            needle = struct.pack(fmt, iid)
            pos = 0
            while True:
                pos = data.find(needle, pos)
                if pos == -1:
                    break
                if hits >= 80:
                    break
                print(f"  item_id {iid} u{width} @ 0x{pos:06X}: {_ctx(data, pos)}")
                hits += 1
                pos += 1
            if hits >= 80:
                break
        if hits >= 80:
            break

    # 3) 关键字
    for kw in KEYWORDS:
        for m in re.finditer(re.escape(kw), data):
            if hits >= 100:
                break
            print(f"  keyword {kw!r} @ 0x{m.start():06X}: {_ctx(data, m.start())}")
            hits += 1
        if hits >= 100:
            break

    print(f"  (显示命中 {min(hits, 100)}/扫描上限)")


def main() -> None:
    for fname in TARGETS:
        p = ORIGIN / fname
        if not p.exists():
            print(f"[skip] {p} 不存在")
            continue
        try:
            data = p.read_bytes()
        except Exception as e:
            print(f"[err] 读 {p} 失败: {e}")
            continue
        scan(fname, data)


if __name__ == "__main__":
    main()
