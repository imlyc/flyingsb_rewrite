"""从 FlyingSB.exe 读原版「地图表」→ assets/map_table.json.

逆向 (map.cpp 加载函数 FUN_004b7b9e / FUN_004b851c):
  表在 VA 0x6474D0, 每项 0x44 字节, 索引 = 位置 ID (.mfo mapname / jmp.m / 剧本表共用的 ID):
    +0x00 u32   flags (1 普通 / 2 ...)
    +0x04 char[9] tileset 资源名 ('#' + 7 字符; exe 自己拼 "p.pcx"/"s.pcx"/"p.mat"/"s.mat")
    +0x0D char[9] map 资源名     ('#' + 7 字符; exe 拼 "p.map"/"p.mfo")
    +0x16 u16   ?
    +0x18 u32   (疑似 BGM 号 / 区域号, -1 = 无)
    +0x20 u32   该地图事件回调函数 VA (代码指针, 多数是空函数 push ebp;mov ebp,esp;pop ebp;ret)
    +0x24 u32   ?
    +0x28 char[24] Big5 显示名 (读档界面/存档 0x04 地点名用的就是它)
  共 500 项 (488.. 为空占位 '#T______').

**这张表是地图 ↔ 图集的唯一真值**: 487 张 .map 里只有 80 张有同名 .pcx, 其余共用别的图集,
靠猜 (同页前缀 / 尺寸) 有 196 张会配错 (如 TBB0___P 实际用 TEV0___P, TGM0___P 有同名图集却用 TDS0___P).

跑法: cd rewrite && venv/bin/python -m tools.extract_map_table
"""
from __future__ import annotations

import json
import os
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORIGIN = Path(os.environ.get("FLYINGSB_ORIGIN", ROOT.parent / "origin" / "flyingsb"))
EXE = Path(os.environ.get("FLYINGSB_EXE", ORIGIN / "FlyingSB.exe"))
OUT = ROOT / "assets" / "map_table.json"
ATTR_OUT = ROOT / "assets" / "map_attr_table.json"

# .map 属性层低 16 位是这张 260 项表的下标 (FUN_004b5ac3): cell = ATTR_TABLE[idx] & ~0x1f
#   | (attr>>16)%4 | ((attr>>18)&7)<<2.  bit9 = 实心, bit5..8 = 四向出边阻挡 (上/下/左/右),
#   bit19..20 = 事件类型 (1=传送/触发), bit21..25 = 事件(jmp)下标, bit26..28 = 朝向.
ATTR_TABLE_VA = 0x6521D4
ATTR_TABLE_N = 0x104

TABLE_VA = 0x6474D0
IMAGE_BASE = 0x400000
STRIDE = 0x44
MAX_ENTRIES = 500


def _cstr(b: bytes) -> str:
    i = b.find(b"\0")
    return (b[:i] if i >= 0 else b).decode("latin1")


def _res_name(raw: str, layer: str) -> str:
    """'#Tbb0___' + 'P' → 'TBB0___P' (extract_dll 落盘的资源名, 大写)."""
    return (raw.lstrip("#") + layer).upper()


def parse(exe: Path = EXE) -> list[dict]:
    data = exe.read_bytes()
    base = TABLE_VA - IMAGE_BASE
    out = []
    for i in range(MAX_ENTRIES):
        e = data[base + i * STRIDE: base + (i + 1) * STRIDE]
        flags = struct.unpack_from("<I", e, 0)[0]
        ts, mp = _cstr(e[4:13]), _cstr(e[13:22])
        if not mp.startswith("#") or mp == "#T______":
            continue
        f18, _f1c, script_va = struct.unpack_from("<iII", e, 0x18)
        name = e[0x28:0x40].decode("big5", errors="replace").strip(" \0")
        out.append({
            "id": i,
            "map": _res_name(mp, "P"),
            "tileset": _res_name(ts, "P"),
            "flags": flags,
            "bgm": f18,
            "script_va": script_va,
            "name": name,
        })
    return out


def parse_attr_table(exe: Path = EXE) -> list[int]:
    data = exe.read_bytes()
    return list(struct.unpack_from(f"<{ATTR_TABLE_N}I", data, ATTR_TABLE_VA - IMAGE_BASE))


def main() -> int:
    rows = parse()
    ATTR_OUT.write_text(json.dumps(parse_attr_table()), encoding="utf-8")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    n_shared = sum(1 for r in rows if r["map"] != r["tileset"])
    print(f"地图表 → {OUT}: {len(rows)} 项, 其中 {n_shared} 张用别的图集")
    for r in rows[:3] + [r for r in rows if r["map"] in ("TBB0___P", "TFI0___P", "TGM0___P")]:
        print(f"  id {r['id']:3d} {r['map']} tileset={r['tileset']} bgm={r['bgm']} {r['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
