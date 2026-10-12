"""宝箱系统 (数据驱动) —— 位置来自 .map 对象层的独立物体格, 内容来自 assets/chests.json.

逆向背景 (见 memory: project_fidelity.md):
  · 宝箱 *位置* 可从 .map 尾部的 8 字节/格 object 层读出: 独立物体格 (object type ∈ {3,7,11,13,15,19,23},
    tail_b == 1, 实例 idx != 0) 里「可通行」的子集即为候选宝箱 (tools/gen_chests.py 自动生成).
  · 宝箱 *内容* (开箱给什么) 在 FlyingSB.exe 的 .data 段, 静态扫描未能定位; 当前 chests.json 为
    TODO 占位, 待 exe 逆向 / 攻略校准. 本模块只负责「位置判定 + 开箱发奖 + 存档标记」.

chests.json 结构:
  {"maps": {base: [{"x":int,"y":int,"item_id":int|null,"qty":int,"note":str}, ...]}}
  item_id 为 None 表示「待填」, 开箱时不发物品只提示空箱.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.items import get_item_name
from core.save_manager import SaveData

ROOT = Path(__file__).resolve().parent.parent
CHESTS_FILE = ROOT / "assets" / "chests.json"
CHEST_FIXES_FILE = ROOT / "assets" / "chest_fixes.json"

_cache: dict | None = None
_fixes: dict | None = None


def _load_fixes() -> dict:
    """`assets/chest_fixes.json`: 少数图宝箱坐标的按图修正 (见 tools/calibrate_chest_coords.py)."""
    global _fixes
    if _fixes is None:
        try:
            _fixes = json.loads(CHEST_FIXES_FILE.read_text(encoding="utf-8"))
        except Exception:
            _fixes = {}
    return _fixes


def _load_all() -> dict:
    global _cache
    if _cache is None:
        if CHESTS_FILE.exists():
            try:
                _cache = json.loads(CHESTS_FILE.read_text(encoding="utf-8")).get("maps", {})
            except Exception:
                _cache = {}
        else:
            _cache = {}
    return _cache


def reload() -> None:
    global _cache
    _cache = None


def chests_for(base: str) -> list[dict]:
    lst = _load_all().get(base, [])
    if not lst:
        return []
    # 按图坐标修正 (assets/chest_fixes.json): 少数图宝箱 y 坐标系颠倒, 如小森林 TBB0___P
    if base in (_load_fixes().get("y_flip") or ()):
        from core import real_map as realm          # 惰性导入, 避免循环依赖
        h = realm.load(base).h
        lst = [dict(c, y=h - 1 - int(c["y"])) for c in lst]
    return list(lst)


def chest_at(base: str, x: int, y: int) -> dict | None:
    for c in chests_for(base):
        if c["x"] == x and c["y"] == y:
            return c
    return None


def _key(base: str, x: int, y: int) -> str:
    return f"{base}:{x}:{y}"


def is_opened(save: SaveData | None, base: str, x: int, y: int) -> bool:
    if save is None:
        return False
    opened = getattr(save, "chests_opened", None)
    return opened is not None and _key(base, x, y) in opened


def open_chest(save: SaveData | None, chest: dict) -> str:
    """开箱: 标记已开, 把物品放进背包. 返回给玩家看的一行提示."""
    base = chest["map"] if "map" in chest else None
    x, y = chest["x"], chest["y"]
    item_id = chest.get("item_id")
    qty = int(chest.get("qty", 1))
    if save is not None and is_opened(save, base, x, y):
        return "（已经空了）"
    if save is not None:
        opened = getattr(save, "chests_opened", None)
        if opened is None:
            opened = []
            save.chests_opened = opened  # type: ignore[attr-defined]
        k = _key(base, x, y)
        if k not in opened:
            opened.append(k)
    if not item_id:
        return "（空宝箱）"
    if save is not None:
        save.inventory.add(item_id, qty)
    return f"获得 {get_item_name(item_id)} ×{qty}"
