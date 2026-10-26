"""从 FlyingSB.exe 提取"敌人表" (静态逆向, ImageBase 0x400000).

敌人记录表 VA **0x68BFF0**, 步长 **0x7C** (31 个 int32), **230 条** (0..225 有效, 226+ 为"身份不詳"空档).
字段语义 2026-10-25 按 exe 消费者逐个确认 (reverse_engineering/xref_enemy_fields.txt, fn_4a6efe.txt, fn_49ff07.txt,
enemy_field_users.txt). 旧版标签整体错位 (把法攻当 HP、HP 当经验…), 已更正:
  +0x00 flags      属性 0xf000000 (相克 FUN_004a663b) / 相性 0x3000 (命中 ±10, FUN_004a6e0d) / 0x20 boss /
                   0x1f00 异常免疫 / 0x2000000 = 属性 2 (打中紫河会触发变身) / 0x10000000 不踩雷
  +0x04 名称指针 (Big5)
  +0x08 class      摆阵前后排 + 反击概率表行 (FUN_004a65b6)
  +0x0c magic_atk  法攻 (法术伤害 = (法攻 + 智力 - 玩家智力) × 威力)
  +0x10 hp         实例 HP (摆阵 FUN_0049ff07 拷到 0x86adb4); 也是回复上限
  +0x14 mp         实例 MP (0x86adb8; 出招扣 招式表 +8)
  +0x18 level      实例等级 (0x86adbc; 高预算遇敌 +3); 进玩家暴击/命中式
  +0x1c ai_mode    传给 AI 寻路 (FUN_004b1084/4b0532)
  +0x20 wisdom     智力 (法伤 / 回复 / MP 吸取)
  +0x24 move10     移动力 × 10 (FUN_004b1286: /10 → FUN_004adf85 可达范围)
  +0x28 evade      闪避 (玩家命中率 - 此值)
  +0x2c attack     攻击
  +0x30 defence    防御 (玩家物理伤害 = 攻击 - 此值)
  +0x34 luck       幸运 (敌命中/暴击 +, 玩家命中/暴击 -)
  +0x38 speed      每回合行动值增量 (FUN_004a4108)
  +0x3c move_count 招式数; +0x40..+0x4c move0..3 招式 id (敌方招式表 0x692f58, 248 项); +0x50..+0x5c weight0..3 出招权重
  +0x60 exp  +0x64 money  +0x68 drop_item  +0x6c drop_rate (千分比, FUN_004a5c63)
  +0x70 unk28  (+0x74 / +0x78 是**下一条**记录的 编号 / 贴图基址: 真记录起点 0x68BFE8 = [编号][贴图基址][flags]...)
  贴图基址 (-0x04) = ps_ 网格登记表 0x5B0008 下标 (core.grid_atlas_table): 本敌人的 ps_XXX00 (+1..+7 同族 01..07).
  2026-10-26 与外部资料包 230 条 fieldKey 全部吻合.

产物: assets/enemy_table.json  {"enemies": {id: {...}}}
跑法: cd rewrite && venv/bin/python -m tools.extract_enemies
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
BASE, STRIDE, COUNT = 0x68BFF0, 0x7C, 230
UNSET = 0xFFFFFFFF
# 索引 -> (字段名, 是否 confirmed)
LABELS = {
    0: "flags", 1: "name_ptr", 2: "class", 3: "magic_atk", 4: "hp", 5: "mp",
    6: "level", 7: "ai_mode", 8: "wisdom", 9: "move10", 10: "evade",
    11: "attack", 12: "defence", 13: "luck", 14: "speed", 15: "move_count",
    16: "move0", 17: "move1", 18: "move2", 19: "move3", 20: "weight0",
    21: "weight1", 22: "weight2", 23: "weight3", 24: "exp", 25: "money",
    26: "drop_item", 27: "drop_rate", 28: "unk28", 29: "next_id", 30: "next_sprite",
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
        rec.pop("next_id", None)
        rec.pop("next_sprite", None)
        rec["sprite_base"] = sgn(struct.unpack_from("<I", raw, o - 4)[0])      # 记录真起点在 -8: [编号][贴图基址]
        from core.grid_atlas_table import grid_atlas_key
        rec["sprite"] = grid_atlas_key(rec["sprite_base"])
        n = max(0, min(4, sgn(f[15])))
        rec["moves"] = [sgn(f[i]) for i in range(16, 16 + n)]            # 敌方招式表下标
        rec["weights"] = [sgn(f[i]) for i in range(20, 20 + n)]
        enemies[str(k)] = rec

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"enemies": enemies}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"敌人 {len(enemies)} 条 → {OUT.relative_to(ROOT)}")
    for k in ("16", "17", "100", "141", "200", "210", "215"):
        if k in enemies:
            e = enemies[k]
            print(f"  id{k:>3s} {e['name']:<8s} Lv{e['level']:>3} HP{e['hp']:>6} 攻{e['attack']:>4} 防{e['defence']:>4} "
                  f"经{e['exp']:>6} 金{e['money']:>5} 招式{e['moves']} 权重{e['weights']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
