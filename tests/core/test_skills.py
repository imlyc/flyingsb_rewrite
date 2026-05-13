"""技能表锚点测试 — skill_id 跟 mod 文档的 hex ID 一一对应."""

from core.skills import SKILLS, get_skill_name


def test_known_doc_anchors():
    """mod 说明文档列出的 hex ID 不能漂."""
    assert get_skill_name(0x00) == '大金刚'
    assert get_skill_name(0x04) == '分身术'
    assert get_skill_name(0x0c) == '圣水'
    assert get_skill_name(0x17) == '凤凰掌'
    assert get_skill_name(0x1d) == '台风火炎炮'
    assert get_skill_name(0x23) == '破天舞'
    assert get_skill_name(0x38) == '火炎喷射器'


def test_mod_added_skills_present():
    """mod 表里多出的 5 个技能 (0x39-0x41), 文档里未列, 但应该 dump 进来."""
    assert get_skill_name(0x39) == '流行冰钻'
    assert get_skill_name(0x41) == '冰龙升天'


def test_unknown_skill_returns_placeholder():
    assert get_skill_name(0xFF) == "未知技能#0xff"


def test_total_skill_count():
    """66 个技能 (0x00 ~ 0x41)."""
    assert len(SKILLS) == 0x42
    assert min(SKILLS) == 0x00
    assert max(SKILLS) == 0x41
