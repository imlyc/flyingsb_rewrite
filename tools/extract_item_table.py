"""从 FlyingSB.exe 提取"物品表": 价格 + 分类 + 装备属性 + 效果 + 描述.

逆向出的结构 (VA, ImageBase=0x400000):
  · 物品记录表基址 **0x6954D4**, 步长 **76 (0x4C)** 字节, 覆盖 id 0..359;
  · 定位方式: 记录 +0x00 是指向物品名字符串(Big5)的指针, 由此锚定后
    `(0x298FE8 - 0x2954D4) / 199 == 76` 整除, 且每项名字与 core/items.py 完全一致.
  · 字段偏移 (19 个 u32):
      +0x00  名称指针
      +0x04  **卖价 (sell)**      商店用 `cmp [rec+0x6954d8], 0; jle 跳过` 筛可卖品
      +0x08  **买价 (buy)**       商店用 `money - 已付  cmp [rec+0x6954dc]` 判断钱够不够
      +0x0C  **类型位 kind** (隊伍情報装备冲突/锁定判定 FUN_004c5281/4c53b2/424162: 0x80 盾类, 0x10 光劍, 0x20 莫亞刀 ...)
      +0x10  **装备附带状态位 abn** (FUN_00433296: 五件 |= 后 &0x1f 写角色表 +8)
      +0x14  分类 cls (0x10 帽 / 0x20 衣 / 0x30 武器 / 0x40 首饰, & 0xF0)
      +0x18  **可装备角色掩码** (bit 0x8000>>角色记录号; 0 = 不可装备)
      +0x1C  **效果类型**: 5=纯装备 / 6=属性药丸 / 10=状态·特殊 / 14=HP·MP回复 / 0=关键道具
      +0x20  **力量 Power**      (装备) / **回复量** (type=14, 10000=全回复)
      +0x24  **智慧 Wisdom**
      +0x28  **敏捷 Agile**
      +0x2C  **攻击 Attack**
      +0x30  **防御 Defence**
      +0x34  **幸运 Luck**
      +0x38  未用
      +0x3C  武器普攻表项 (装备到手部时写角色表 +0x74, 见 FUN_0042a9ae)
      +0x40  效果处理函数指针 (仅可用道具)
      +0x44  **描述指针** (Big5)
      +0x48  id + 1
  · 代码访问模式: `imul reg, reg, 0x4c` + `[reg + 0x6954xx]`.
  · **属性归属的铁证** (VA 0x4334b0..0x4335a8, 装备应用函数):
      char[0x689da8] Power   += item[+0x20]   (0x6954f4)
      char[0x689dac] Wisdom  += item[+0x24]   (0x6954f8)
      char[0x689db0] Agile   += item[+0x28]   (0x6954fc)
      char[0x689db4] Attack  += item[+0x2c]   (0x695500)
      char[0x689db8] Defence += item[+0x30]   (0x695504)
      char[0x689dbc] Luck    += item[+0x34]   (0x695508)
  · 价格用 -1 (0xFFFFFFFF) 表示"不可买 / 不可卖".
  · 玩家金钱全局 = 0x867e7c (见 F 的商店扣钱点).

产物: assets/items_table.json
  {"items": {id: {"name","buy","sell","cat","slot","type","val",
                   "stats":{"pow","wis","agi","atk","def","luk"},
                   "fx","desc"}}}
跑法: cd rewrite && venv/Scripts/python -m tools.extract_item_table
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
OUT = ROOT / "assets" / "items_table.json"

TABLE_VA = 0x6954D4        # 物品记录表 (VA)
STRIDE = 76                # 0x4C
COUNT = 356                # id 0..355
OFF_NAME, OFF_SELL, OFF_BUY, OFF_CAT = 0x00, 0x04, 0x08, 0x14
CAT_NAME = {0x10: "HAT", 0x20: "CLOTHES", 0x30: "WEAPON", 0x40: "ACCESSORY"}
UNAVAILABLE = -1
STAT_KEYS = ("pow", "wis", "agi", "atk", "def", "luk")


def _signed(v: int) -> int:
    return v - 0x100000000 if v & 0x80000000 else v


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not EXE.exists():
        print(f"[skip] 找不到 exe: {EXE}")
        return 1
    raw = EXE.read_bytes()
    img = 0x400000

    def big5(va: int, maxlen: int = 64) -> str:
        o = va - img
        if not (0 <= o < len(raw)):
            return ""
        e = raw.find(b"\x00", o)
        return raw[o:(e if 0 < e < o + maxlen else o + maxlen)].decode("big5", "replace")

    try:
        from opencc import OpenCC
        cc = OpenCC("t2s")
    except Exception:
        cc = None

    items: dict[str, dict] = {}
    for i in range(COUNT):
        o = TABLE_VA - img + i * STRIDE
        if o + STRIDE > len(raw):
            break
        f = struct.unpack_from("<19I", raw, o)
        name_va, sell, buy, cat = f[0], f[1], f[2], f[5]
        stats = {k: _signed(f[8 + n]) for n, k in enumerate(STAT_KEYS)}
        desc_raw = big5(f[17])
        desc = cc.convert(desc_raw) if cc else desc_raw
        items[str(i)] = {
            "name": big5(name_va),
            "buy": buy if buy != 0xFFFFFFFF else UNAVAILABLE,
            "sell": sell if sell != 0xFFFFFFFF else UNAVAILABLE,
            "cat": CAT_NAME.get(cat & 0xF0),
            "slot": f[6],
            "kind": f[3],
            "abn": f[4],
            "cls": f[5],
            "type": f[7],
            "val": _signed(f[8]),
            "stats": {k: v for k, v in stats.items() if v},
            "fx": f[16],
            "desc": desc,
        }

    # 交叉校验: 表里的名字(t2s 后)必须与 core/items.py 一致, 否则说明表偏移不对
    sys.path.insert(0, str(ROOT))
    from core.items import get_item_name
    if cc is None:
        print("[skip] 无 opencc, 跳过名字校验")
    else:
        bad = [i for i in range(COUNT)
               if i != 354 and items[str(i)]["name"]
               and cc.convert(items[str(i)]["name"]) != get_item_name(i)]
        if bad:
            print(f"[warn] {len(bad)} 项名字与 core/items.py 不一致, 例: "
                  + ", ".join(f"{i}:{items[str(i)]['name']}!={get_item_name(i)}" for i in bad[:5]))
        else:
            print("名字校验: 全部通过 (原版表 = core/items.py)")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    priced = [v for v in items.values() if v["buy"] > 0]
    equippable = [v for v in items.values() if v["slot"]]
    print(f"物品 {len(items)} 项, 可购买 {len(priced)} 项, 可装备 {len(equippable)} 项 "
          f"→ {OUT.relative_to(ROOT)}")
    for i in ("1", "124", "128", "208", "213", "299", "305", "318"):
        v = items[i]
        print(f"  id {i:>3s} {v['name']:<10s} 买{v['buy']:>7} type={v['type']:>2} "
              f"slot={v['slot']:>6} stats={v['stats']} desc={v['desc'][:20]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
