"""装备规则 — 照 exe 隊伍情報/裝備 菜单逆向 (2026-10-27, reverse_engineering/eqmenu_decomp.java):

  FUN_00433296  换装后重算: 力/智/敏/攻/防/运 = 角色表裸值 (Unknow_2..7, +0x24..+0x38) + 五件装备加成
                (exe 只在装备菜单里调用它: 进 裝備 子菜单 / 换装后各一次; 新游戏/战斗都不调)
  FUN_00432c3f  左上属性面板的 当前值 / 换上后值 (param 0 = 现值, 1 = 假设换上); 智慧 >999 减 1000 (exe 怪癖), 负数→0
  FUN_00424162  某槽可选列表: 背包里数量 >0 + 可装备角色位 (0x8000 >> 角色记录号) + 分类 (+0x14 & 0xf0);
                頭/身/飾 首项 "解除裝備", 手部没有 (武器不能卸); 每项 可选/灰显 判定见 candidates()
  FUN_004c5281  其它槽装备的 kind 位 (+0x0c) 之或;  FUN_004c53b2 该槽是否允许更换
  FUN_0042a9ae  case 0x1e: 旧装备 +1 回背包, 新装备 -1, 写槽, 重算; 精靈 (0xe6) 给美娜技能 0x13 (表 +0xb8)

背包抽象: count(id) / add(id, n) / remove(id, n) (core.inventory.Inventory 即可; 竞技场用 SandboxInventory).
"""
from __future__ import annotations

from core.character import UNSET, Character
from core.items import item_table_entry

SLOT_FIELDS = ("Head", "Body", "Hand", "Accessories1", "Accessories2")
SLOT_CLASS = (0x10, 0x20, 0x30, 0x40, 0x40)          # 物品 +0x14 & 0xf0
UNEQUIP = -0x80000000                                 # 列表里的 "解除裝備" 项 (exe 0x80000000)
STAT_KEYS = ("pow", "wis", "agi", "atk", "def", "luk")
BASE_FIELDS = ("Unknow_2", "Unknow_3", "Unknow_4", "Unknow_5", "Unknow_6", "Unknow_7")
FINAL_FIELDS = ("Power", "Wisdom", "Agile", "Attack", "Defence", "Luck")
ITEM_COUNT = 0x168                                    # exe 遍历道具 0..359
SPIRIT_ITEM, SPIRIT_SKILL = 0xE6, 0x13                # 精靈 → 美娜 召喚精靈


def _i32(v: int) -> int:
    v = int(v) & 0xFFFFFFFF
    return v - 0x100000000 if v & 0x80000000 else v


def slot_item(ch: Character, slot: int) -> int | None:
    v = _i32(getattr(ch, SLOT_FIELDS[slot]))
    return None if v < 0 else v


def equipped(ch: Character) -> list[int | None]:
    return [slot_item(ch, s) for s in range(5)]


def _e(item: int) -> dict:
    return item_table_entry(item) or {}


def item_kind(item: int) -> int:
    return int(_e(item).get("kind", 0) or 0)


_CAT_CLS = {"HAT": 0x10, "CLOTHES": 0x20, "WEAPON": 0x30, "ACCESSORY": 0x40}


def item_class(item: int) -> int:
    e = _e(item)
    if "cls" not in e:                       # 旧版 items_table.json (无 cls 字段) → 按分类名
        return _CAT_CLS.get(e.get("cat") or "", 0)
    return int(e.get("cls", 0) or 0) & 0xF0


def item_char_mask(item: int) -> int:
    return int(_e(item).get("slot", 0) or 0)


def item_bonus(item: int | None) -> tuple[int, ...]:
    if item is None:
        return (0,) * 6
    st = _e(item).get("stats") or {}
    return tuple(int(st.get(k, 0)) for k in STAT_KEYS)


def can_wear(record: int, item: int) -> bool:
    """可装备角色位: item+0x18 & (0x8000 >> 角色记录号)."""
    return bool(item_char_mask(item) & (0x8000 >> (record & 0x1F)))


# ---------------- 属性 ----------------
def _sum_stats(ch: Character, items) -> list[int]:
    out = [_i32(getattr(ch, f)) for f in BASE_FIELDS]
    for it in items:
        if it is not None and it >= 0:
            for k, b in enumerate(item_bonus(it)):
                out[k] += b
    return out


def recompute_stats(ch: Character) -> None:
    """FUN_00433296: 最终 力/智/敏/攻/防/运 = 裸值 + 五件装备加成 (无截断)."""
    for f, v in zip(FINAL_FIELDS, _sum_stats(ch, equipped(ch))):
        setattr(ch, f, v)


def _clamp(vals: list[int]) -> list[int]:
    while vals[1] > 999:                 # exe 只对智慧做 -1000 折返
        vals[1] -= 1000
    return [max(0, v) for v in vals]


def current_stats(ch: Character) -> list[int]:
    """FUN_00432c3f(c, 0): 面板左列 = 角色表现值."""
    return _clamp([_i32(getattr(ch, f)) for f in FINAL_FIELDS])


def preview_stats(ch: Character, slot: int, item: int | None) -> list[int]:
    """FUN_00432c3f(c, 1): 该槽换成 item (None = 解除) 后的值 (裸值 + 五件加成)."""
    items = equipped(ch)
    items[slot] = item
    return _clamp(_sum_stats(ch, items))


# ---------------- 可选列表 ----------------
def kinds_except(ch: Character, slot: int) -> int:
    """FUN_004c5281: 除 slot 外已装备物品的 kind 位之或 (slot=5 → 五件全部)."""
    k = 0
    for s, it in enumerate(equipped(ch)):
        if it is not None and s != slot:
            k |= item_kind(it)
    return k


def slot_changeable(ch: Character, slot: int) -> bool:
    """FUN_004c53b2: 该槽装备是否允许更换 (被其它装备锁住时返回 False)."""
    allk = kinds_except(ch, 5)
    other = kinds_except(ch, slot)
    cur = slot_item(ch, slot)
    if cur is None:
        return True
    ck = item_kind(cur)
    if slot == 0:
        return not (allk & 1)
    if slot == 1:
        return not ((ck & 4) == 4 and (other & 0x18))
    if slot == 2:
        return not ((ck & 0x20) == 0x20 and (other & 0x40))
    return not ((ck & 2) == 2 and (other & 4))


def _acc_ok(k: int, o: int) -> bool:
    if (k & 0x80) and (o & 0x80):
        return False
    if (k & 0x40) and not (o & 0x20):
        return False
    if (k & 8) and not (o & 4):
        return False
    if (k & 0x300) and (o & 0x300):
        return False
    if (k & 0xC00) and (o & 0xC00):
        return False
    return True


def candidates(ch: Character, record: int, slot: int, inv) -> list[tuple[int, bool]]:
    """FUN_00424162: [(道具 id 或 UNEQUIP, 可选)], 顺序 = 解除裝備 + 道具 id 升序."""
    other = kinds_except(ch, slot)
    can = slot_changeable(ch, slot)
    out: list[tuple[int, bool]] = []
    if slot != 2:
        out.append((UNEQUIP, can and slot_item(ch, slot) is not None))
    want = SLOT_CLASS[slot]
    for it in range(ITEM_COUNT):
        if inv.count(it) <= 0 or item_class(it) != want or not can_wear(record, it):
            continue
        en = can
        k = item_kind(it)
        if can:
            if slot == 1 and k == 4 and not (other & 2):
                en = False
            elif slot == 2 and k == 0x10 and not (other & 4):
                en = False
            elif slot >= 3:
                en = _acc_ok(k, other)
        out.append((it, en))
    return out


# ---------------- 换装 ----------------
def equip(ch: Character, slot: int, item: int | None, inv, name: str | None = None) -> None:
    """FUN_0042a9ae case 0x1e: 旧装备回背包, 新装备出背包, 写槽, 重算属性. item=None → 解除."""
    old = slot_item(ch, slot)
    if old is not None:
        inv.add(old, 1)
    setattr(ch, SLOT_FIELDS[slot], UNSET if item is None else item)
    if item is not None:
        inv.remove(item, 1)
    if name == "美娜" and getattr(ch, "skills", None):
        has = SPIRIT_ITEM in (slot_item(ch, 3), slot_item(ch, 4))
        sk = [s for s in ch.skills if s != SPIRIT_SKILL]
        if has:
            sk.append(SPIRIT_SKILL)
        ch.skills = sk
    recompute_stats(ch)


class SandboxInventory:
    """竞技场沙盒背包: 每种道具都有 COUNT 个, 增减不生效 (列表数量栏显示 99)."""

    COUNT = 99

    def count(self, item_id: int) -> int:
        return self.COUNT if 0 <= item_id < ITEM_COUNT and _e(item_id) else 0

    def add(self, item_id: int, n: int = 1) -> None:
        pass

    def remove(self, item_id: int, n: int = 1) -> bool:
        return True
