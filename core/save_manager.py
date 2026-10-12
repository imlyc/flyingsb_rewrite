"""原版 Save*.dat 二进制存档解析器 (15232 bytes, little-endian).

文件布局:
  0x0000          DWORD   行/状态标记
  0x0004          24B     地点名 (Big5, 空格 padding)
  0x001C          DWORD   0
  0x0020-0x002C   5×DWORD 游戏状态 (chapter, map ID, X, Y, ...)
  0x0030-0x0043   zeros
  0x0044-0x0C03   16×188B 角色块 (每块 4B identifier + 28×DWORD Character + 18×DWORD extra)
                  - Block 0-11: 12 个角色槽 (含 2 个 gap)
                  - Block 12-15: 推测为 NPC/敌人模板, 暂不解析
  0x0BF4          DWORD   金钱
  0x0C04+         其他    库存/剧情 flags (暂不解析)
"""

from __future__ import annotations

import os
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

from core.character import (
    CHARACTER_NAMES,
    GAP_SLOTS,
    PLAYABLE_SLOTS,
    TOTAL_SLOTS,
    UNSET,
    Character,
)
from core.items import get_item_name
from core.inventory import Inventory
from core import party as party_mod

SAVE_SIZE = 15232
HEADER_SIZE = 0x44                # 68 bytes
BLOCK_SIZE = 0xBC                 # 188 bytes per character block
CHAR_DATA_OFFSET_IN_BLOCK = 4     # block 前 4B 是 identifier, 跳过
CHARACTERS_START = 0x44
MONEY_OFFSET = 0xBF4
FLAGS_START = 0xC04          # 角色块之后的剧情 flags 位图区 (1 = 已置位)
FLAGS_END = 0x1C00


@dataclass
class SaveData:
    location: str                              # Big5 解码后的地点名
    flag: int                                  # offset 0x00 的 DWORD
    state: tuple[int, ...]                     # offset 0x20 的 5 个 DWORD
    money: int
    characters: dict[int, Character]           # slot -> Character (含 gap)
    flags: bytes = field(repr=False)           # 剧情 flags 位图 (FLAGS_START..FLAGS_END)
    raw: bytes = field(repr=False)
    inventory: Inventory = field(default_factory=Inventory)  # 背包 (本 remake 自控模型)
    chests_opened: list = field(default_factory=list)         # 已开宝箱 key 列表 "base:x:y"
    world_visited: list = field(default_factory=list)         # 去过的世界地图位置 ID (M 键地图显示)

    @property
    def progress(self) -> int:
        """章节/剧情进度 (state[2], 实测随进度变化: 新档 0 → 进度档 19)."""
        return self.state[2] if len(self.state) > 2 else 0

    def flag_bit(self, idx: int) -> bool:
        return bool((self.flags[idx // 8] >> (idx % 8)) & 1)

    def set_flag_bits(self) -> list[int]:
        """所有置 1 的 flag 位下标."""
        out = []
        for byte_i, byte in enumerate(self.flags):
            if byte:
                for bit in range(8):
                    if (byte >> bit) & 1:
                        out.append(byte_i * 8 + bit)
        return out


def load_save(path: str | Path) -> SaveData:
    full = Path(path).read_bytes()
    if len(full) < SAVE_SIZE:
        raise ValueError(f"Save file too small: expected >= {SAVE_SIZE}, got {len(full)}")
    data = full[:SAVE_SIZE]                     # 原版 15232 字节区域

    flag = struct.unpack_from("<I", data, 0x00)[0]
    location_raw = data[0x04:0x1C]
    try:
        location = location_raw.decode("big5", errors="replace").rstrip(" \x00")
    except Exception:
        location = location_raw.hex()

    state = struct.unpack_from("<5I", data, 0x20)
    money = struct.unpack_from("<I", data, MONEY_OFFSET)[0]

    characters: dict[int, Character] = {}
    for slot in range(TOTAL_SLOTS):
        block_off = CHARACTERS_START + slot * BLOCK_SIZE
        char_off = block_off + CHAR_DATA_OFFSET_IN_BLOCK
        ch = Character.from_bytes(data, char_off)
        # extra[3..12] = 已学技能列表 (10 槽, -1 空); 与 exe 角色定义表同位置
        extra = struct.unpack_from("<18I", data, block_off + CHAR_DATA_OFFSET_IN_BLOCK + 112)
        ch.skills = [v for v in extra[3:13] if v != UNSET and v >= 0]
        characters[slot] = ch

    # 背包: 原版库存区 (开关位图+变量) 需 exe 逆向才能解码, 此处为 0;
    # 若文件带本 remake 的 INV trailer 则解析之.
    inventory = Inventory()
    if len(full) > SAVE_SIZE:
        inv = Inventory.from_bytes(full[SAVE_SIZE:])
        if inv is not None:
            inventory = inv

    return SaveData(
        location=location,
        flag=flag,
        state=state,
        money=money,
        characters=characters,
        inventory=inventory,
        flags=data[FLAGS_START:FLAGS_END],
        raw=data,
    )


def new_game_save() -> SaveData:
    """复刻原版「新游戏」: 主角 **美娜** 开局, 其余槽位为空 (未加入)。

    仅激活美娜 (slot 2); 后续角色由剧情 beat 完成时的
    `party_mod.activate_character` 写入对应槽位。
    """
    characters: dict[int, Character] = {}
    for slot in range(TOTAL_SLOTS):
        characters[slot] = Character(
            MaxHP=0, CurrentHP=0, MaxMP=0, CurrentMP=0, Level=0, SG=0,
            Unknow_1=0, Exp=0, nextExp=0,
            Unknow_2=0, Unknow_3=0, Unknow_4=0, Unknow_5=0, Unknow_6=0,
            Unknow_7=0, Unknow_8=0,
            Power=0, Wisdom=0, Agile=0, Attack=0, Defence=0, Luck=0,
            Unknow_9=0,
            Head=UNSET, Body=UNSET, Hand=UNSET,
            Accessories1=UNSET, Accessories2=UNSET,
        )
    # 激活美娜 (slot 2) — 初始数值/装备来自 exe 角色定义表 (core.character_data)
    mina = party_mod.make_character("美娜")
    characters[party_mod.NAME_TO_SLOT["美娜"]] = mina
    # 初始背包 (占位)
    inventory = Inventory()
    inventory.add(299, 3)    # 恢复药 x3
    inventory.add(300, 2)    # 良药 x2
    inventory.add(305, 1)    # 仙桃 x1
    return SaveData(
        location="",
        flag=0,
        state=(0, 0, 0, 0, 0),
        money=800,  # 起始金: 覆盖前3章唯一花费 (c2 嗜酒老人 300G), 避免软锁
        characters=characters,
        inventory=inventory,
        flags=bytes(FLAGS_END - FLAGS_START),
        raw=bytes(SAVE_SIZE),
    )


def save_save(save: SaveData, path: str | Path) -> None:
    """写出 .dat: 原版 15232 区域 (save.raw) + 本 remake 背包 trailer.

    原版库存区暂未解码 (需 exe 逆向), 故背包走独立 trailer, 不动前 15232 字节,
    原版存档经本函数写出后仍可被原版读取 (尾部为多余字节, 原版忽略).
    """
    raw = save.raw
    if len(raw) != SAVE_SIZE:
        raw = bytes(SAVE_SIZE)
    Path(path).write_bytes(bytes(raw) + save.inventory.to_bytes())


def _fmt_signed(v: int) -> str:
    """无符号 DWORD: 0xFFFFFFFF 显示为 -1."""
    return "-1" if v == UNSET else str(v)


def print_character(slot: int, ch: Character) -> None:
    name = CHARACTER_NAMES.get(slot, "?")
    tag = " (空槽)" if slot in GAP_SLOTS else ""
    print(f"--- Slot {slot:2d}: {name}{tag} ---")
    print(f"  等级 Lv{ch.Level}    HP {ch.CurrentHP}/{ch.MaxHP}    MP {ch.CurrentMP}/{ch.MaxMP}    SG {_fmt_signed(ch.SG)}")
    print(f"  经验 Exp={ch.Exp}  下一级 nextExp={ch.nextExp}")
    print(f"  力量 Pow={ch.Power}  智慧 Wis={ch.Wisdom}  敏捷 Agi={ch.Agile}  攻击 Atk={ch.Attack}  防御 Def={ch.Defence}  幸运 Lck={ch.Luck}")
    print(f"  装备 头={get_item_name(ch.Head)}  身={get_item_name(ch.Body)}  手={get_item_name(ch.Hand)}  饰1={get_item_name(ch.Accessories1)}  饰2={get_item_name(ch.Accessories2)}")


def print_save(save: SaveData) -> None:
    print("=" * 60)
    print(f"地点: {save.location}")
    print(f"金钱: {save.money}")
    print(f"背包: {save.inventory}")
    print(f"标记: flag=0x{save.flag:X}  state={save.state}")
    print("=" * 60)
    for slot in range(TOTAL_SLOTS):
        print_character(slot, save.characters[slot])


# ---------- 测试入口 ----------
# 原版全剧情存档 (repo 上一级 origin/, 可用 FLYINGSB_SAVE 环境变量覆盖), __main__ 自测用
DEFAULT_TEST_SAVE = os.environ.get(
    "FLYINGSB_SAVE",
    str(Path(__file__).resolve().parents[2] / "origin" / "flyingsb"
        / "工具大全" / "存档" / "全剧情存档" / "0" / "Save1.dat"),
)


def _verify_sunwukong(save: SaveData) -> None:
    """对照 Ch0 / Save1.dat 的已知值, 校验解析正确."""
    sw = save.characters[1]
    expected = dict(MaxHP=35, CurrentHP=35, MaxMP=16, CurrentMP=16,
                    Level=2, Exp=115, nextExp=105, Hand=128)
    failures = [(k, v, getattr(sw, k)) for k, v in expected.items() if getattr(sw, k) != v]
    if failures:
        print("\n!!! 校验失败:")
        for k, exp, got in failures:
            print(f"  {k}: expected={exp}, got={got}")
        sys.exit(1)
    print("\n✓ 孙悟空字段校验通过 (Lv2 / HP35 / MP16 / Exp115 / Hand=128 如意)")


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TEST_SAVE
    print(f"Loading: {path}")
    save = load_save(path)
    print_save(save)
    if path == DEFAULT_TEST_SAVE:
        _verify_sunwukong(save)


if __name__ == "__main__":
    main()
