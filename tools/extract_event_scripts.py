"""从 FlyingSB.exe 导出事件脚本 → assets/script/events.json, 以及 FC 渲染用的三张表 → assets/fc_tables.json.

事件脚本 VM 的格式/语义见 core/event_script.py 顶部注释. 这里只做数据导出, 游戏运行时不再需要 exe.

fc_tables.json:
  sheets   {sheet_id: [名字, 列, 行, 锚x, 锚y]}      角色图集表 VA 0x5B0008, 0x34/项 (FC +0x130 = sheet id;
                                                      npc_sprites 的"全局帧号" = (sheet_id-8)*24 + 帧)
  fm_groups {组号: pcx 名}                             战斗帧表 VA 0x5BF8A8, 0x30/项, 6610 帧 → 按 +0x10 组号归并
                                                      (事件脚本 61/62 op 的 mode0 动画 = 组号 + 帧, 帧矩形见 core.fm_frames)
  fc_defs  {fc_id: {"sheet": 初始图集}}                 FC 定义表 VA 0x54EAD0, 0x44/项, +0x38 = sheet id
  dir_rows [8]                                        朝向 → 图集行 (VA 0x65302C)

跑法: cd rewrite && venv/bin/python -m tools.extract_event_scripts
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

from core.event_script import EXE, IMAGE_BASE, ExeImage, build_bundle, event_entries

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "script" / "events.json"
OUT_TABLES = ROOT / "assets" / "fc_tables.json"

SHEET_TABLE_VA, SHEET_STRIDE, SHEET_MAX = 0x5B0008, 0x34, 1400
FRAME_TABLE_VA, FRAME_STRIDE, FRAME_COUNT = 0x5BF8A8, 0x30, 0x19D2
FCDEF_TABLE_VA, FCDEF_STRIDE, FCDEF_COUNT = 0x54EAD0, 0x44, 0x29C
DIR_ROWS_VA = 0x65302C


def fc_tables(img: ExeImage) -> dict:
    d = img.data
    sheets = {}
    for i in range(SHEET_MAX):
        o = SHEET_TABLE_VA - IMAGE_BASE + i * SHEET_STRIDE
        nm = d[o:o + 16].split(b"\0")[0].decode("latin1", "replace")
        if nm:
            cols, rows, ax, ay = struct.unpack_from("<hhhh", d, o + 0x10)
            sheets[i] = [nm.lstrip("!").upper().removesuffix(".PCX"), cols, rows, ax, ay]
    groups: dict[int, str] = {}
    for i in range(FRAME_COUNT):
        o = FRAME_TABLE_VA - IMAGE_BASE + i * FRAME_STRIDE
        nm = d[o:o + 16].split(b"\0")[0].decode("latin1", "replace")
        g = struct.unpack_from("<I", d, o + 0x10)[0]
        groups.setdefault(g, nm.lstrip("@").upper().removesuffix(".PCX"))
    fc_defs = {}
    for i in range(FCDEF_COUNT):
        o = FCDEF_TABLE_VA - IMAGE_BASE + i * FCDEF_STRIDE
        fid, sheet = struct.unpack_from("<I", d, o)[0], struct.unpack_from("<I", d, o + 0x38)[0]
        if fid == i:
            fc_defs[i] = {"sheet": sheet}
    return {"sheets": sheets, "fm_groups": groups, "fc_defs": fc_defs,
            "dir_rows": list(struct.unpack_from("<8I", d, DIR_ROWS_VA - IMAGE_BASE))}


def main() -> int:
    if not EXE.exists():
        print(f"缺 {EXE}")
        return 2
    img = ExeImage(EXE)
    bundle = build_bundle(img)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    n_cmd = sum(len(v) for v in bundle["scripts"].values())
    print(f"事件脚本 → {OUT}: {len(bundle['events'])} 个事件, {len(bundle['scripts'])} 段脚本, {n_cmd} 条指令")
    tables = fc_tables(img)
    OUT_TABLES.write_text(json.dumps(tables, ensure_ascii=False), encoding="utf-8")
    print(f"FC 表 → {OUT_TABLES}: {len(tables['sheets'])} 图集, {len(tables['fm_groups'])} fm 组, "
          f"{len(tables['fc_defs'])} FC 定义; 组26={tables['fm_groups'].get(26)} sheet80={tables['sheets'].get(80)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
