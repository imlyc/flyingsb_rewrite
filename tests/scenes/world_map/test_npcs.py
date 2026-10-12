"""地图 NPC 图层 (scenes.world_map.npcs) 的测试 (A 接入)."""

from __future__ import annotations

import pytest

from core import map_npcs
from scenes.world_map.npcs import NpcLayer

pytestmark = pytest.mark.skipif(
    not map_npcs.available(),
    reason="assets/map_npcs.json 未生成 (先跑 tools.extract_map_npcs)")


def test_layer_counts():
    layer = NpcLayer("TAL0___P")
    assert layer.count == 14
    assert layer.dialogue_count == 13


def test_talkable_tiles_block():
    """有对白的角色挡路 (撞上去触发); 无对白的装饰角色可穿过."""
    layer = NpcLayer("TAL0___P")
    assert layer.blocks(7, 9) is True                 # script 349, 有对白
    assert layer.blocks(12, 1) is False               # script 9 = default
    assert layer.at(7, 9)["script"] == 349


def test_layer_without_data_is_empty():
    layer = NpcLayer("T_LOC0_P")                      # 世界地图上没有角色
    assert layer.count == 0
    assert layer.blocks(3, 3) is False
    assert layer.at(3, 3) is None


def test_hint_roundtrip():
    layer = NpcLayer("TAL0___P")
    assert layer.hint() is None
    layer.set_hint(layer.at(7, 9))
    hint = layer.hint()
    assert hint is not None and "最富有" in hint[0] and hint[1] == (7, 9)
    layer.set_hint(None)
    assert layer.hint() is None


def test_missing_map_is_safe():
    layer = NpcLayer("NOT_A_MAP")
    assert layer.count == 0
    assert layer.blocks(0, 0) is False
