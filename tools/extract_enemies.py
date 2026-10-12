"""从 FlyingSB.exe 提取"敌人表" (静态逆向, ImageBase 0x400000).

逆向出的结构:
  · 敌人记录表 VA **0x68BFF0**, 步长 **0x7C (124)** 字节, 约 216 条 (索引 = .mfo 的 enemytype id).
    (证据: 战斗摆阵函数 0x49ff07 用 `imul idx,0x7c; [reg+0x68bff8]`;
     伤害函数 0x4a7be2 用 `eax=[rec+0x68c01c]; sub eax,[角色 Defence]` → 攻击.)
  · 字段 (见 FIELDS; 已证实的标注 confirmed, 其余为推断):
      +0x04  名称指针 (Big5)                              confirmed
      +0x0C  **HP**                                        confirmed (0x4aaa62)
      +0x10  **经验奖励**                                   (高值, 与战斗结算一致)
      +0x14  **金钱奖励**
      +0x18  **AI 行动组 id** (×0x24 索引行动表)             confirmed
      +0x2C  **攻击**                                      confirmed (攻击 - 角色防御)
      +0x20  魔/防御相关 (从角色 Wisdom 里减去)              推断
      +0x08  阵型位 (0/1/2)                                confirmed
      +0x3C  变体/等级序号
      +0x40..+0x5C  技能表 (0..0x41 有效, -1 空)
      +0x68  掉落物 id
      +0x78  精灵帧基址
      其余为原始保留 (raw).

产物: assets/enemy_table.json  {"enemies": {id: {...}}}
跑法: cd rewrite && venv/Scripts/python -m tools.extract_enemies
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
OUT = ROOT / "assets" / "enemy_table.json"

IMG = 0x400000
BASE, STRIDE, COUNT = 0x68BFF0, 0x7C, 216
UNSET = 0xFFFFFFFF
# 索引 -> (字段名, 是否 confirmed)
LABELS = {
    0: "flags", 1: "name_ptr", 2: "formation", 3: "hp", 4: "exp", 5: "money",
    6: "ai_group", 7: "unk7", 8: "magic_def", 9: "unk9", 10: "unk10",
    11: "attack", 12: "unk12", 13: "unk13", 14: "unk14", 15: "variant",
    16: "skill0", 17: "skill1", 18: "skill2", 19: "skill3", 20: "unk20",
    21: "unk21", 22: "unk22", 23: "unk23", 24: "unk24", 25: "unk25",
    26: "drop_item", 27: "unk27", 28: "unk28", 29: "record_id", 30: "sprite_frame",
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not EXE.exists():
        print(f"[skip] 找不到 exe: {EXE}")
        return 1
    raw = EXE.read_bytes()

    def sgn(v: int) -> int:
        return -1 if v == UNSET else (v - 0x100000000 if v & 0x80000000 else v)

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

    enemies: dict[str, dict] = {}
    for k in range(COUNT):
        o = BASE - IMG + k * STRIDE
        if o + STRIDE > len(raw):
            break
        f = struct.unpack_from("<31I", raw, o)
        name = big5(f[1])
        if not name:
            continue
        rec = {LABELS[i]: sgn(f[i]) for i in range(31)}
        rec["name"] = name
        rec.pop("name_ptr", None)
        # 技能: 字段 16..19 (0..0x41 有效); 掉落物: 字段 20..23 + 26
        rec["skills"] = [sgn(f[i]) for i in range(16, 20) if 0 <= sgn(f[i]) <= 0x41]
        rec["drops"] = [sgn(f[i]) for i in list(range(20, 24)) + [26]
                        if 0 <= sgn(f[i]) <= 355]
        enemies[str(k)] = rec

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"enemies": enemies}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"敌人 {len(enemies)} 条 → {OUT.relative_to(ROOT)}")
    for k in ("16", "17", "100", "141", "200", "210", "215"):
        if k in enemies:
            e = enemies[k]
            print(f"  id{k:>3s} {e['name']:<8s} HP{e['hp']:>4} 攻{e['attack']:>4} "
                  f"经{e['exp']:>6} 金{e['money']:>4} 技能{e['skills']} 掉{e['drops']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
