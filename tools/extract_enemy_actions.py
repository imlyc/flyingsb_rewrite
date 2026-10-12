"""从 FlyingSB.exe 提取「敌方行动表」(战斗 AI 用的动作表).

逆向出的结构 (ImageBase 0x400000):
  · 行动表 VA **0x692F54**, 步长 **0x20 (32)**, 共 **248** 条; 记录:
      +0x00 名称指针 (Big5, 如 "用刀攻擊" / "施放火牆")
      +0x04 参数 A (多为 100/150 = 命中率?)
      +0x08 标志位 (bit 0x800000 = 远程; 其余为范围/特效标志)
      +0x0C/+0x10/+0x14 参数 (目标类型 / 范围 / 序列号)
      +0x18 执行函数指针 (动作演出/伤害结算入口)
      +0x1C id + 1
  · **单位结构 +0xE8 = 当前行动 id**; 访问点 `mov ecx,[unit+0xE8]; shl ecx,5;
    mov edx,[ecx+0x692F54]` (战斗演出 0x4CFF33): 由此取动作名/标志/执行函数.
  · 敌人的「AI 行为组」在敌人记录 +0x18 (ai_group, 实测 1..50), 摆阵时写入单位
    (**单位 +0x86ADBC**), 并偶尔 +3 做变化 (= 行为随机化).

产物: assets/enemy_actions.json  {"actions": {id: {...}}}
跑法: cd rewrite && venv/Scripts/python -m tools.extract_enemy_actions
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
OUT = ROOT / "assets" / "enemy_actions.json"
IMG = 0x400000
BASE, STRIDE, COUNT = 0x692F54, 0x20, 248


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not EXE.exists():
        print(f"[skip] 找不到 exe: {EXE}")
        return 1
    raw = EXE.read_bytes()

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

    actions: dict[str, dict] = {}
    for k in range(COUNT):
        o = BASE - IMG + k * STRIDE
        if o + STRIDE > len(raw):
            break
        f = struct.unpack_from("<8I", raw, o)
        name = big5(f[0])
        if not name:
            continue
        actions[str(k)] = {
            "name": name,
            "param_a": f[1],
            "flags": f[2],
            "ranged": bool(f[2] & 0x800000),
            "p3": f[3],
            "p4": f[4],
            "p5": f[5],
            "func": f[6],
            "id1": f[7],
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"actions": actions}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"行动 {len(actions)} 条 → {OUT.relative_to(ROOT)}")
    for k in ("0", "1", "2", "3", "4", "5"):
        a = actions.get(k)
        if a:
            print(f"  id{k:>3s} {a['name']:<10s} ranged={a['ranged']} "
                  f"flags={a['flags']:#x} func={a['func']:#x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
