"""技能表锚点测试 — skill_id 跟 mod 文档的 hex ID 一一对应."""

from core.skills import (
    CHARACTER_SKILL_POOL,
    SKILL_DESCRIPTIONS,
    SKILLS,
    default_skills_for,
    get_skill_desc,
    get_skill_name,
)


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


def test_character_skill_pool_covers_all_skills():
    """10 角色 × 各自 skill 段 = 66, 无重叠, 无遗漏 (= exe 设计)."""
    union: set[int] = set()
    for pool in CHARACTER_SKILL_POOL.values():
        for sid in pool:
            assert sid not in union, f"skill {sid:#04x} 被分给多个角色"
            union.add(sid)
    assert union == set(SKILLS.keys())


def test_default_skills_known_anchors():
    # 孙悟空 → 0x00..0x09; 蒙面人 → 0x20..0x24 (五招特能)
    assert default_skills_for("孙悟空")[0] == 0x00
    assert default_skills_for("孙悟空")[-1] == 0x09
    assert default_skills_for("蒙面人") == list(range(0x20, 0x25))
    assert get_skill_name(default_skills_for("蒙面人")[3]) == "破天舞"


def test_default_skills_unknown_name_empty():
    assert default_skills_for("不存在角色") == []


def test_skill_desc_table_complete():
    """66 个 desc 一一对应 SKILLS."""
    assert len(SKILL_DESCRIPTIONS) == len(SKILLS)
    assert set(SKILL_DESCRIPTIONS.keys()) == set(SKILLS.keys())


def test_skill_desc_anchors():
    """关键技能描述锚点 (= exe Big5 dump + t2s, 跟截图比对)."""
    assert get_skill_desc(0x20) == '垂直下砍的功夫。'
    assert get_skill_desc(0x00).startswith('变成金刚')
    assert get_skill_desc(0x09) == '猴子与凤凰合体，将全体人员复原。'


def test_skill_desc_unknown_empty():
    assert get_skill_desc(0xFF) == ""
