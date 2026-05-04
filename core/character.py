"""角色数据结构, 对应原版 C++ struct Character (pragma pack 16, 28 DWORDs = 112 bytes)."""

from __future__ import annotations

import struct
from dataclasses import dataclass

UNSET = 0xFFFFFFFF  # 装备槽 / SG 未设置时的值


@dataclass
class Character:
    MaxHP: int
    CurrentHP: int
    MaxMP: int
    CurrentMP: int
    Level: int
    SG: int
    Unknow_1: int
    Exp: int
    nextExp: int
    Unknow_2: int
    Unknow_3: int
    Unknow_4: int
    Unknow_5: int
    Unknow_6: int
    Unknow_7: int
    Unknow_8: int
    Power: int
    Wisdom: int
    Agile: int
    Attack: int
    Defence: int
    Luck: int
    Unknow_9: int
    Head: int
    Body: int
    Hand: int
    Accessories1: int
    Accessories2: int

    SIZE = 28 * 4  # 112 bytes

    @classmethod
    def from_bytes(cls, buf: bytes, offset: int = 0) -> "Character":
        fields = struct.unpack_from("<28I", buf, offset)
        return cls(*fields)

    def to_bytes(self) -> bytes:
        return struct.pack(
            "<28I",
            self.MaxHP, self.CurrentHP, self.MaxMP, self.CurrentMP,
            self.Level, self.SG, self.Unknow_1, self.Exp, self.nextExp,
            self.Unknow_2, self.Unknow_3, self.Unknow_4, self.Unknow_5,
            self.Unknow_6, self.Unknow_7, self.Unknow_8,
            self.Power, self.Wisdom, self.Agile, self.Attack,
            self.Defence, self.Luck, self.Unknow_9,
            self.Head, self.Body, self.Hand, self.Accessories1, self.Accessories2,
        )


# 12 个槽位中, 0 和 7 是空槽 (gap), 其余对应 10 个可玩角色
CHARACTER_NAMES: dict[int, str] = {
    0: "<gap>",
    1: "孙悟空",
    2: "美娜",
    3: "三藏法师",
    4: "猪八戒",
    5: "沙悟净",
    6: "蒙面人",
    7: "<gap>",
    8: "乐神杰特",
    9: "破无",
    10: "捕山",
    11: "紫河",
}

PLAYABLE_SLOTS = [1, 2, 3, 4, 5, 6, 8, 9, 10, 11]
GAP_SLOTS = [0, 7]
TOTAL_SLOTS = 12
