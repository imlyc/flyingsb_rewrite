"""角色数据结构, 对应原版 C++ struct Character (pragma pack 16, 28 DWORDs = 112 bytes)."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

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
    # 存档角色块 extra[3..12] = **已学技能列表** (10 槽). 不计入 28 DWORD 结构;
    # 载入原版存档时填入, 战斗用 (见 core/battle/setup.unit_from_character).
    skills: list = field(default_factory=list)

    SIZE = 28 * 4  # 112 bytes

    @classmethod
    def from_bytes(cls, buf: bytes, offset: int = 0) -> "Character":
        fields = struct.unpack_from("<28I", buf, offset)
        return cls(*fields)

    def to_bytes(self) -> bytes:
        # 统一按 uint32 掩码 (SG/-1 等负值也要能回写, 见 save_manager 的 UNSET 约定)
        vals = (
            self.MaxHP, self.CurrentHP, self.MaxMP, self.CurrentMP,
            self.Level, self.SG, self.Unknow_1, self.Exp, self.nextExp,
            self.Unknow_2, self.Unknow_3, self.Unknow_4, self.Unknow_5,
            self.Unknow_6, self.Unknow_7, self.Unknow_8,
            self.Power, self.Wisdom, self.Agile, self.Attack,
            self.Defence, self.Luck, self.Unknow_9,
            self.Head, self.Body, self.Hand, self.Accessories1, self.Accessories2,
        )
        return struct.pack("<28I", *[int(v) & 0xFFFFFFFF for v in vals])


# 槽位 = **exe 角色定义表记录号** (存档角色块顺序与定义表一致, 已用存档实证:
# slot1 悟空[技能0-9]/魔风双截棍, slot3 美娜[10-18]/轮小刀, slot4 三藏[20-24],
# slot5 八戒[25-29], slot6 沙悟净[30,31], slot8 蒙面人[32-35], slot9 乐神[37-46],
# slot10 破无[47-51], slot11 捕山[52-55], slot12 紫河[57-65]).
# 0/2 是悟空的备用定义, 7 = 迪特(不可玩), 13-15 是紫河备用定义.
CHARACTER_NAMES: dict[int, str] = {
    1: "孙悟空",
    3: "美娜",
    4: "三藏法师",
    5: "猪八戒",
    6: "沙悟净",
    8: "蒙面人",
    9: "乐神杰特",
    10: "破无",
    11: "捕山",
    12: "紫河",
}

PLAYABLE_SLOTS = [1, 3, 4, 5, 6, 8, 9, 10, 11, 12]
GAP_SLOTS = [0, 2, 7, 13, 14, 15]
TOTAL_SLOTS = 16      # 存档角色块区 = 16 块 (每块 0xBC; 0x44 + 16*0xBC = 0xC04)
