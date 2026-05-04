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

SAVE_SIZE = 15232
HEADER_SIZE = 0x44                # 68 bytes
BLOCK_SIZE = 0xBC                 # 188 bytes per character block
CHAR_DATA_OFFSET_IN_BLOCK = 4     # block 前 4B 是 identifier, 跳过
CHARACTERS_START = 0x44
MONEY_OFFSET = 0xBF4


@dataclass
class SaveData:
    location: str                              # Big5 解码后的地点名
    flag: int                                  # offset 0x00 的 DWORD
    state: tuple[int, ...]                     # offset 0x20 的 5 个 DWORD
    money: int
    characters: dict[int, Character]           # slot -> Character (含 gap)
    raw: bytes = field(repr=False)


def load_save(path: str | Path) -> SaveData:
    data = Path(path).read_bytes()
    if len(data) != SAVE_SIZE:
        raise ValueError(f"Save file size mismatch: expected {SAVE_SIZE}, got {len(data)}")

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
        characters[slot] = Character.from_bytes(data, char_off)

    return SaveData(
        location=location,
        flag=flag,
        state=state,
        money=money,
        characters=characters,
        raw=data,
    )


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
    print(f"标记: flag=0x{save.flag:X}  state={save.state}")
    print("=" * 60)
    for slot in range(TOTAL_SLOTS):
        print_character(slot, save.characters[slot])


# ---------- 测试入口 ----------
DEFAULT_TEST_SAVE = (
    "/Users/imlyc/Work/flyingsb/origin/flyingsb/工具大全/存档/全剧情存档/0/Save1.dat"
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
