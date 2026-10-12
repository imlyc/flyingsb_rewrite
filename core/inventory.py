"""背包 (物品栏) 模型.

原版存档的库存区 (0xC04..0x38D8) 用 "开关位图(拥有)+变量(数量)" 的
id→位/索引映射存储, 精确解码需逆向 exe (长期任务). 因此本 remake 用一套
自控、自洽的背包模型:

  - Inventory.slots: dict[item_id -> count]
  - 序列化: 在 .dat 末尾追加一个带 magic 的 trailer (不影响原版前 15232 字节)

消耗品 / 装备的战斗效果来自 core.items 的占位表 (标 TODO, 待 exe 逆向补全).
"""

from __future__ import annotations

import struct

from core.items import ITEMS, ItemCategory, get_item_category, get_item_name

# trailer 魔法字 + 版本
INV_MAGIC = b"INV1"


class Inventory:
    """物品栏: item_id -> 数量."""

    def __init__(self, slots: dict[int, int] | None = None) -> None:
        self.slots: dict[int, int] = {i: c for i, c in (slots or {}).items() if c > 0}

    # ------- 基本操作 -------
    def add(self, item_id: int, n: int = 1) -> None:
        if n <= 0:
            return
        self.slots[item_id] = self.slots.get(item_id, 0) + n

    def remove(self, item_id: int, n: int = 1) -> bool:
        """尝试减 n 个; 不足返回 False 且不改动."""
        if self.slots.get(item_id, 0) < n:
            return False
        self.slots[item_id] -= n
        if self.slots[item_id] <= 0:
            del self.slots[item_id]
        return True

    def count(self, item_id: int) -> int:
        return self.slots.get(item_id, 0)

    def has(self, item_id: int, n: int = 1) -> bool:
        return self.slots.get(item_id, 0) >= n

    # ------- 分类视图 -------
    def consumables(self) -> list[tuple[int, int]]:
        return [(i, c) for i, c in self.slots.items()
                if get_item_category(i) is ItemCategory.CONSUMABLE]

    def equipment(self) -> list[tuple[int, int]]:
        return [(i, c) for i, c in self.slots.items()
                if get_item_category(i) is not ItemCategory.CONSUMABLE and i != 0]

    def sorted(self) -> list[tuple[int, int]]:
        """按 (分类顺序, id) 排序, 便于 UI 展示."""

        def key(kv: tuple[int, int]):
            cat = get_item_category(kv[0])
            order = cat.value if cat is not None else ""
            return (order, kv[0])

        return sorted(self.slots.items(), key=key)

    def total(self) -> int:
        return sum(self.slots.values())

    def __repr__(self) -> str:
        return "Inventory(" + ", ".join(
            f"{get_item_name(i)}x{c}" for i, c in self.sorted()
        ) + ")"

    # ------- 序列化 (trailer, 追加在 .dat 之后) -------
    def to_bytes(self) -> bytes:
        pairs = self.sorted()
        out = bytearray(INV_MAGIC)
        out += struct.pack("<I", len(pairs))
        for i, c in pairs:
            out += struct.pack("<II", i, c)
        return bytes(out)

    @classmethod
    def from_bytes(cls, data: bytes) -> "Inventory | None":
        """解析 trailer; 不是本格式返回 None."""
        if not data.startswith(INV_MAGIC):
            return None
        body = data[len(INV_MAGIC):]
        if len(body) < 4:
            return cls({})
        (cnt,) = struct.unpack_from("<I", body, 0)
        slots: dict[int, int] = {}
        off = 4
        for _ in range(cnt):
            if off + 8 > len(body):
                break
            i, c = struct.unpack_from("<II", body, off)
            off += 8
            if c > 0:
                slots[i] = c
        return cls(slots)
