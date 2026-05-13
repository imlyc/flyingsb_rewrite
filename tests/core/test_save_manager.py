"""存档解析锚点测试 — 用全剧情存档/0 校验 Character 字段映射不漂."""

import pathlib

import pytest

from core.character import TOTAL_SLOTS
from core.save_manager import (
    BLOCK_SIZE,
    CHARACTERS_START,
    HEADER_SIZE,
    MONEY_OFFSET,
    SAVE_SIZE,
    load_save,
)


_DEFAULT_SAVE = pathlib.Path(
    "/Users/imlyc/Work/flyingsb/origin/flyingsb/工具大全/存档/全剧情存档/0/Save1.dat"
)


@pytest.fixture(scope="module")
def save():
    if not _DEFAULT_SAVE.exists():
        pytest.skip(f"reference save not found: {_DEFAULT_SAVE}")
    return load_save(_DEFAULT_SAVE)


def test_save_constants():
    """存档结构基础常量, 不能漂."""
    assert SAVE_SIZE == 15232
    assert HEADER_SIZE == 0x44
    assert BLOCK_SIZE == 0xBC          # 188 bytes/角色
    assert CHARACTERS_START == 0x44
    # 16 角色 × 188 = 3008; HEADER_SIZE + 16*BLOCK_SIZE = 0xC04
    assert CHARACTERS_START + 16 * BLOCK_SIZE == 0xC04
    assert MONEY_OFFSET == 0xBF4


def test_sunwukong_anchor_fields(save):
    """孙悟空 Slot 1 是核心校验锚点: Lv2 / HP35 / MP16 / Exp115 / Hand=128(如意双截棍).
    如果哪天 BLOCK_SIZE / CHARACTERS_START 偏移漂了, 这里会立刻炸."""
    sw = save.characters[1]
    assert sw.Level == 2
    assert sw.MaxHP == 35
    assert sw.CurrentHP == 35
    assert sw.MaxMP == 16
    assert sw.CurrentMP == 16
    assert sw.Exp == 115
    assert sw.nextExp == 105
    assert sw.Hand == 128         # 对应 items.py ID 128 = '如意双截棍'


def test_money_field(save):
    """金钱字段在 0xBF4."""
    assert save.money == 2049


def test_location_decoded(save):
    """地点字符串能解码 (Big5)."""
    assert save.location  # 非空


def test_all_slots_present(save):
    """character.py 定义 TOTAL_SLOTS=12 (10 个 PLAYABLE + 2 个 GAP). 全 slot 都要有 entry."""
    assert TOTAL_SLOTS == 12
    assert len(save.characters) == TOTAL_SLOTS
    for slot in range(TOTAL_SLOTS):
        assert slot in save.characters
