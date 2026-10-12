"""分析 .map 尾部 8 字节/格的 object/event 层.

输出:
  - 每张地图的 tail 长度/覆盖率
  - 按 map 聚合的非默认 tail 模式 (高频优先)
  - "可疑"模式: 高频出现且与常见建筑对象 high 值 (3/7/9/11/13/15/19/23) 不同者,
    可能是宝箱/传送/事件点.

用法:
    cd rewrite && venv/Scripts/python -m tools.analyze_map_tail
"""

from __future__ import annotations

import struct
from collections import Counter, defaultdict
from pathlib import Path

MAPS_DIR = Path(__file__).resolve().parent.parent / "assets" / "maps"
HEADER_U32 = 120

# 目前观察到的 attr>>16 对象类型(建筑/树等), 供可疑模式筛选.
COMMON_OBJECT_HIGH = {0, 3, 7, 9, 11, 13, 15, 19, 23}


def tail_for(base: str) -> list[tuple[int, int]] | None:
    p = MAPS_DIR / f"{base}.map"
    if not p.exists():
        return None
    raw = p.read_bytes()
    if len(raw) < HEADER_U32 * 4:
        return None
    u = list(struct.unpack("<%dI" % (len(raw) // 4), raw[: len(raw) // 4 * 4]))
    w, h = u[6], u[7]
    cells = w * h
    tail_off = (HEADER_U32 + 2 * cells) * 4
    tail_len = len(raw) - tail_off
    if tail_len < cells * 8:
        return None
    return [struct.unpack_from("<II", raw, tail_off + i * 8) for i in range(cells)]


def analyze(base: str, tail: list[tuple[int, int]], w: int, h: int) -> None:
    c = Counter(tail)
    empty = c.get((0, 0), 0) + c.get((1, 1), 0)
    total = w * h
    used = total - empty
    print(f"\n=== {base} {w}x{h}  tail_used={used}/{total} ({100*used/total:.1f}%)")
    patterns = c.most_common(12)
    for vals, cnt in patterns:
        tag = "(empty)" if vals in ((0, 0), (1, 1)) else ""
        a, b = vals
        a_high = a >> 16
        b_high = b >> 16
        suspicious = "  <== 可疑" if a_high not in COMMON_OBJECT_HIGH and a != 0 else ""
        print(f"  {str(vals):26s}  cnt={cnt:4d}  a_high=0x{a_high:04X}  b_high=0x{b_high:04X} {tag}{suspicious}")


def main() -> None:
    bases = sorted(p.stem for p in MAPS_DIR.glob("*.map"))
    # 先只看有尾部的图(城镇/迷宫)
    found = 0
    for base in bases:
        tail = tail_for(base)
        if tail is None:
            continue
        # 解析 w/h 需要重新读; 为简单直接读
        raw = (MAPS_DIR / f"{base}.map").read_bytes()
        u = list(struct.unpack("<%dI" % (len(raw) // 4), raw[: len(raw) // 4 * 4]))
        w, h = u[6], u[7]
        analyze(base, tail, w, h)
        found += 1
    print(f"\n共 {found}/{len(bases)} 张地图有尾部 object/event 层.")


if __name__ == "__main__":
    main()
