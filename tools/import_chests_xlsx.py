"""从 `幻想西游记_全宝箱数据.xlsx`(光盘版权威表) 生成 assets/chests.json.

数据源: 仓库根目录 ../幻想西游记_全宝箱数据.xlsx, Sheet「宝箱总表」(表头在第 5 行).
列: 宝箱ID/显示序号/地图ID/地图资源名(=base)/MFO地图名/游戏显示中文名/X/Y/.../道具ID/道具名/...

产出: {"maps": {base: [{"x","y","item_id","qty","note"}, ...]}}
  · x,y = 原始光盘坐标 (与 .map object 层一致)
  · item_id 取自 xlsx「道具ID」(需与 core.items 的 engine_id 空间一致, 脚本会校验)
  · note 记中文物品名, 便于人工核对

跑法: cd rewrite && venv/Scripts/python -m tools.import_chests_xlsx
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT.parent / "幻想西游记_全宝箱数据.xlsx"
OUT = ROOT / "assets" / "chests.json"


def _load_xlsx(path: Path) -> list[dict]:
    z = zipfile.ZipFile(path)
    ss = z.read("xl/sharedStrings.xml").decode("utf-8")
    strs = [re.sub(r"<[^>]+>", "", s) for s in re.findall(r"<si>(.*?)</si>", ss, re.S)]
    sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8")

    def cell_val(c: str) -> str:
        m = re.search(r"<v>(.*?)</v>", c, re.S)
        if not m:
            return ""
        v = m.group(1)
        return strs[int(v)] if 't="s"' in c else v

    rows = []
    for r in re.findall(r"<row[^>]*>(.*?)</row>", sheet, re.S):
        d: dict[str, str] = {}
        for c in re.findall(r"(<c\b[^>]*>.*?</c>|<c\b[^>]*/>)", r, re.S):
            rm = re.search(r'r="([A-Z]+)\d+"', c)
            if rm:
                d[rm.group(1)] = cell_val(c)
        rows.append(d)

    hi = next(i for i, d in enumerate(rows) if "宝箱ID" in d.values())
    cols = {v: k for k, v in rows[hi].items()}
    out = []
    for d in rows[hi + 1:]:
        base = d.get(cols["地图资源名"], "")
        if not base or not d.get(cols["宝箱ID"], ""):
            continue
        out.append({
            "base": base,
            "x": int(float(d.get(cols["X"], "0"))),
            "y": int(float(d.get(cols["Y"], "0"))),
            "item_id": int(float(d.get(cols["道具ID"], "-1"))),
            "name": d.get(cols["道具名"], ""),
            "cnt": d.get(cols["游戏显示中文名"], ""),
            "off": d.get(cols["源偏移"], ""),
        })
    return out


def main() -> int:
    if not XLSX.exists():
        print(f"[err] 找不到 {XLSX}")
        return 1
    rows = _load_xlsx(XLSX)
    print(f"xlsx 有效宝箱行: {len(rows)}, 地图数: {len({r['base'] for r in rows})}")

    # 校验 item_id 空间与 core.items 是否一致
    from core.items import get_item_name
    bad = 0
    for r in rows:
        nm = get_item_name(r["item_id"])
        if not nm.startswith("未知") and r["name"] and nm != r["name"]:
            bad += 1
            if bad <= 12:
                print(f"  [id不符] {r['base']} id={r['item_id']} items='{nm}' xlsx='{r['name']}'")
    print(f"item_id 名字不一致: {bad}/{len(rows)} (0=完全一致)")

    maps: dict[str, list[dict]] = {}
    for r in rows:
        maps.setdefault(r["base"], []).append({
            "x": r["x"], "y": r["y"], "item_id": r["item_id"], "qty": 1,
            "note": f"{r['name']} (xlsx 源偏移 {r['off']})",
        })
    for v in maps.values():
        v.sort(key=lambda c: (c["y"], c["x"]))
    OUT.write_text(json.dumps({"maps": maps}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"写入 {OUT}: {len(maps)} 张地图, {sum(len(v) for v in maps.values())} 个宝箱")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
