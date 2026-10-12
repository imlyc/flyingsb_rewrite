"""core.map_npcs / core.script_text 的测试 (A: 地图角色 → 原版对白)."""

from __future__ import annotations

import pytest

from core import map_npcs
from core import script_text

pytestmark = pytest.mark.skipif(
    not map_npcs.available(),
    reason="assets/map_npcs.json 未生成 (先跑 tools.extract_map_npcs)")


def test_alxia_has_npcs():
    """阿尔夏(TAL0___P) 有 14 个角色, 13 个能说出原版对白."""
    ns = map_npcs.npcs_for("TAL0___P")
    assert len(ns) == 14
    assert sum(1 for n in ns if script_text.has_dialogue(n["script"])) == 13


def test_npc_at_and_blocked():
    npc = map_npcs.npc_at("TAL0___P", 7, 9)
    assert npc is not None and npc["script"] == 349
    assert map_npcs.npc_at("TAL0___P", 0, 0) is None
    assert (7, 9) in map_npcs.blocked_tiles("TAL0___P")


def test_default_script_has_no_dialogue():
    """script 1..13 是原版 default 分支 (占位英文串), 不算对白."""
    assert script_text.has_dialogue(18) is True
    assert script_text.has_dialogue(5) is False
    assert "无对白" in script_text.first_line(5)


def test_to_messages_splits_by_dialogue_box():
    """`;` 分对话框: 349 是 2 句, 18 是 1 句."""
    msgs = script_text.to_messages(349)
    assert len(msgs) == 2
    assert "最富有" in msgs[0]["text"]
    assert "狄阿曼" in msgs[1]["text"]
    assert msgs[0]["scene"] == 349
    assert len(script_text.to_messages(18)) == 1


def test_to_messages_for_default_branch():
    msgs = script_text.to_messages(5)
    assert len(msgs) == 1
    assert "没有对白" in msgs[0]["text"]


def test_wuzhi_village_statue_lines():
    """五指村雕像剧情 (script 18~21) 能正确解出."""
    assert "五指村" in script_text.to_messages(18)[0]["text"]
    assert "五行山" in script_text.to_messages(19)[0]["text"]
    assert "神像" in script_text.to_messages(20)[0]["text"]


def test_unknown_script_id():
    assert script_text.to_messages(99999) == []
