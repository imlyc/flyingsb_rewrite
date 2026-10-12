"""原版存档解码: 角色块顺序 = exe 角色定义表记录号; extra[3..12] = 已学技能列表."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SAVE1 = ROOT / "saveData" / "Save1.dat"

pytestmark = pytest.mark.skipif(not SAVE1.exists(), reason="缺 saveData/Save1.dat")


def test_save_slot_order_matches_record_and_skills():
    from core.character import CHARACTER_NAMES, PLAYABLE_SLOTS
    from core.save_manager import load_save

    s = load_save(SAVE1)
    # 槽位 = 定义表记录号 (已用装备/技能双向印证)
    assert CHARACTER_NAMES[1] == "孙悟空"
    assert CHARACTER_NAMES[3] == "美娜"
    assert CHARACTER_NAMES[12] == "紫河"
    # extra[3..12] = 已学技能列表, 与各自技能池吻合
    assert s.characters[1].skills == list(range(10))          # 悟空 0..9
    assert s.characters[3].skills[:9] == list(range(10, 19))  # 美娜 10..18
    assert s.characters[6].skills == [30, 31]                 # 沙悟净 (剧情学)
    # 全队 10 人都在
    assert len(PLAYABLE_SLOTS) == 10
