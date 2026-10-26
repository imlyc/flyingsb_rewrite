"""从 FlyingSB.exe 提取"角色定义表 / 成长表 / 经验表" (静态逆向, ImageBase 0x400000).

逆向出的结构:
  · **角色定义表**: VA **0x689d64**, 步长 **0xBC (188)**, 16 条记录 (与存档角色块同布局).
      +0x00  名称指针 (Big5)
      +0x04  28×DWORD Character (同 core.character.Character 字段顺序)
      +0x74  18×DWORD extra (前 2 个是精灵帧基址; 之后疑为初始技能等)
    这是**新游戏 (Lv1) 的初始数值 + 初始装备**! 例: 孙悟空 MaxHP30 MaxMP13 攻16 防16
    初装 Head22/Body65/Hand121; 美娜 MaxHP25 初装 Body65/Hand129 ...
  · **裸装基础攻/防/运** 存在 Character 的 Unknow_5/6/7 (index 12/13/14) —— 由装备应用函数
    (0x4334b0) 与升级逻辑证实 (见 memory project_fidelity).
  · **成长表**:
      0x64422C: [角色记录号] -> 成长组 id G
      0x64412C: [G*4 + i] -> 行号 (i=0..3 = 最大HP / 最大MP / 基础攻击 / 基础防御; -1 = 不成长)
      0x6429B8: 成长行, 每行 100×DWORD (对应 Lv1..99), 升级到 L 级时 += 行[L]
  · **经验表**: VA **0x642670**, [Lv] -> 达到下一级所需**累计**经验 (Lv1=100, Lv2=220, ...)

产物: assets/characters_table.json
跑法: cd rewrite && venv/Scripts/python -m tools.extract_characters
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
OUT = ROOT / "assets" / "characters_table.json"

IMG = 0x400000
CHAR_BASE, CHAR_STRIDE, CHAR_COUNT = 0x689d64, 0xBC, 16
GROUP_MAP = 0x64422C          # charIdx -> growth group
GROUP_ROWS = 0x64412C         # group*4 + i -> row id
ROW_BASE, ROW_STRIDE, ROW_LEVELS = 0x6429B8, 400, 100
EXP_BASE, EXP_COUNT = 0x642670, 100
UNSET = 0xFFFFFFFF
FIELD_NAMES = [
    "MaxHP", "CurrentHP", "MaxMP", "CurrentMP", "Level", "SG", "Unknow_1",
    "Exp", "nextExp", "Unknow_2", "Unknow_3", "Unknow_4", "Unknow_5", "Unknow_6",
    "Unknow_7", "Unknow_8", "Power", "Wisdom", "Agile", "Attack", "Defence",
    "Luck", "Unknow_9", "Head", "Body", "Hand", "Accessories1", "Accessories2",
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not EXE.exists():
        print(f"[skip] 找不到 exe: {EXE}")
        return 1
    raw = EXE.read_bytes()

    def u32(va: int, n: int = 1) -> list[int]:
        return list(struct.unpack_from(f"<{n}I", raw, va - IMG))

    def big5(va: int) -> str:
        o = va - IMG
        if not (0 <= o < len(raw)):
            return ""
        e = raw.find(b"\x00", o)
        if e < 0 or e - o > 40:
            return ""
        try:
            return raw[o:e].decode("big5")
        except Exception:
            return raw[o:e].decode("big5", "replace")

    def sgn(v: int) -> int:
        return -1 if v == UNSET else (v - 0x100000000 if v & 0x80000000 else v)

    exp_table = u32(EXP_BASE, EXP_COUNT)
    group_map = u32(GROUP_MAP, CHAR_COUNT)
    group_rows = u32(GROUP_ROWS, 64)          # 16 组 × 4 行 (0x64412C..0x64422C)

    chars: list[dict] = []
    rows_used: dict[int, list[int]] = {}
    for k in range(CHAR_COUNT):
        base = CHAR_BASE + k * CHAR_STRIDE
        name = big5(u32(base)[0])
        fields = u32(base + 4, 28)
        extra = [sgn(v) for v in u32(base + 4 + 112, 18)]
        if not name:
            break
        rec = {"record": k, "name": name, "sprite_base": extra[0],
               "fields": {FIELD_NAMES[i]: sgn(fields[i]) for i in range(28)},
               # extra[3..12] = **初始技能列表** (10 槽, -1 空); 与存档同位置
               # (存档里这 10 槽会随等级学习而填满, 见 memory: 悟空 0..9 / 美娜 10..18)
               "initial_skills": [s for s in extra[3:13] if s >= 0]}
        # 成长组
        g = group_map[k] if k < len(group_map) else -1
        row_ids = [sgn(group_rows[g * 4 + i]) for i in range(4)] if 0 <= g < 16 else []
        rec["growth_group"] = g
        rec["growth_rows"] = row_ids          # [HP行, MP行, 攻击行, 防御行]
        for r in row_ids:
            if r >= 0 and r not in rows_used:
                rows_used[r] = u32(ROW_BASE + r * ROW_STRIDE, ROW_LEVELS)
        chars.append(rec)

    out = {
        "characters": chars,
        "growth_rows": {str(r): v for r, v in rows_used.items()},
        "exp_table": exp_table,
        "field_order": FIELD_NAMES,
        "base_stat_note": "裸装基础攻/防/运 = Unknow_5/Unknow_6/Unknow_7; "
                          "Attack/Defence/Luck 为含装备的最终值",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"角色 {len(chars)} 条, 成长行 {len(rows_used)} 条, 经验表 {len(exp_table)} 项 "
          f"→ {OUT.relative_to(ROOT)}")
    for c in chars[:6]:
        f = c["fields"]
        print(f"  {c['name']:<6s} Lv{f['Level']} HP{f['MaxHP']:>3} MP{f['MaxMP']:>3} "
              f"基础攻{f['Unknow_5']:>3} 防{f['Unknow_6']:>3} 运{f['Unknow_7']:>2} "
              f"装备 头{f['Head']}/身{f['Body']}/手{f['Hand']} 成长行{c['growth_rows']}")
    print("  经验表前 8:", exp_table[:8])
    return 0


if __name__ == "__main__":
    sys.exit(main())
