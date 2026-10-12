"""角色/敌人真实数据测试 (源自 FlyingSB.exe; 缺 assets 自动 skip)."""

import pytest

from core import character_data

_have_chars = bool(character_data.records())
_have_data = _have_chars


@pytest.mark.skipif(not _have_chars, reason="缺 assets/characters_table.json")
def test_starting_stats_real():
    """美娜 Lv1 真实初始值 + 初始装备 (exe 角色定义表)."""
    s = character_data.starting_stats("美娜")
    assert s is not None
    assert s["MaxHP"] == 25 and s["MaxMP"] == 15
    assert s["Body"] == 65 and s["Hand"] == 129        # 薄衣 / 刀
    assert s["Head"] == 0xFFFFFFFF                     # 无头饰


@pytest.mark.skipif(not _have_chars, reason="缺 assets/characters_table.json")
def test_exp_table_real():
    """经验表: Lv1→2 需 100, Lv2→3 需 220 (原版累计阈值)."""
    assert character_data.exp_needed(1) == 100
    assert character_data.exp_needed(2) == 220
    assert character_data.exp_needed(0) == 0


@pytest.mark.skipif(not _have_chars, reason="缺 assets/characters_table.json")
def test_level_up_growth():
    """升级按成长表加 最大HP/MP/攻/防, 且回满."""
    ch = character_data.make_character("美娜")
    assert ch is not None
    before_hp, before_lv = ch.MaxHP, ch.Level
    character_data.level_up(ch, "美娜", 2)
    assert ch.Level == 2
    assert ch.MaxHP >= before_hp          # 成长行有 HP 增量
    assert ch.CurrentHP == ch.MaxHP       # 升级回满


@pytest.mark.skipif(not _have_chars, reason="缺 assets/characters_table.json")
def test_add_exp_levels():
    """加大量经验应连升多级并消耗经验表."""
    ch = character_data.make_character("美娜")
    gained = character_data.add_exp(ch, "美娜", 360)
    assert ch.Level >= 3                  # 100+220 可到 Lv3
    assert gained and gained[0] == 2


@pytest.mark.skipif(not _have_data, reason="缺 assets/enemy_table.json")
def test_enemy_table_real():
    """敌人表: id17 = 羊頭怪, 真实 HP/攻击/经验."""
    e = character_data.enemy(17)
    assert e is not None
    assert e["name"] == "羊頭怪"
    assert e["hp"] == 180
    assert e["attack"] == 370
    assert e["exp"] == 12000
    assert 48 in e["skills"] or 49 in e["skills"]


@pytest.mark.skipif(not _have_chars, reason="缺 assets/characters_table.json")
def test_skill_learn_levels():
    """技能学习表 (exe 0x64216C): 按等级解锁 + 开局技能."""
    from core.skills import SKILLS
    # 孙悟空: 开局无技能, Lv2 学会 大金刚, Lv4 再学 猛将神君青龙
    assert character_data.learned_skills("孙悟空", 1) == []
    lv4 = [SKILLS[s] for s in character_data.learned_skills("孙悟空", 4)]
    assert lv4 == ["大金刚", "猛将神君青龙"]
    # 美娜: 开局只有 小回复 (角色定义表 extra[3..12] = [10]), Lv4 学会 疗毒 (表首项)
    start = [SKILLS[s] for s in character_data.starting_skills("美娜")]
    assert start == ["小回复"]
    assert character_data.skill_learn_table("美娜")[0] == (4, 11)
    assert 11 in character_data.learned_skills("美娜", 4)
    assert 11 not in character_data.learned_skills("美娜", 3)
    # 沙悟净: 学习表为空, 技能靠剧情 (向忍者 NPC 学) → 入队后可用 (2 个)
    assert character_data.starting_skills("沙悟净") == []      # 无"开局就会"
    assert character_data.story_skills("沙悟净") == [0x1E, 0x1F]  # 斗转星移 / 返荷杖
    assert len(character_data.learned_skills("沙悟净", 1)) == 2


@pytest.mark.skipif(not _have_data, reason="缺 assets/enemy_table.json")
def test_make_enemy_by_type():
    from core.battle.setup import make_enemy_by_type
    u = make_enemy_by_type(17)
    assert u is not None
    assert u.name == "羊頭怪"
    assert u.max_hp == 180 and u.attack == 370
    assert u.exp_reward == 12000
    # 未知类型 → None
    assert make_enemy_by_type(99999) is None
