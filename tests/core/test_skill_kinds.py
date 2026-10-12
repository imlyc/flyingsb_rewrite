"""技能类别 (治疗/复活/辅助) + 回血量 (原版描述驱动)."""

from core.skills import (
    HEAL_AMOUNT,
    skill_kind,
    targets_allies,
)
from core.skill_seq import heal_amount, is_heal_skill


def test_skill_kind_basic():
    assert skill_kind(0x0A) == "heal"     # 小回复
    assert skill_kind(0x0E) == "heal"     # 大恢复
    assert skill_kind(0x11) == "heal"     # 超回复
    assert skill_kind(0x0F) == "revive"   # 苏生
    assert skill_kind(0x12) == "revive"   # 重生
    assert skill_kind(0x0B) == "cure"     # 疗毒
    assert skill_kind(0x28) == "buff"     # 强力桑巴
    assert skill_kind(0x0D) == "drain"    # 移血
    assert skill_kind(0x00) == "attack"   # 大金刚
    assert skill_kind(0x30) == "attack"   # 三角箭


def test_targets_allies():
    assert targets_allies(0x0A)      # 小回复 打友军
    assert targets_allies(0x0F)      # 苏生
    assert not targets_allies(0x00)  # 大金刚 打敌人
    assert not targets_allies(0x30)  # 三角箭


def test_is_heal_skill_covers_party_heals():
    """美娜的一系列回复技都算治疗 (之前只认 0x15)."""
    for sid in (0x0A, 0x0E, 0x11, 0x15, 0x26, 0x2C):
        assert is_heal_skill(sid)
    assert not is_heal_skill(0x00)


def test_heal_amount_from_description():
    class _U:
        attack = 10
    assert heal_amount(_U(), 0x0A) == 100     # 小回复: 描述 100
    assert heal_amount(_U(), 0x0E) == 500     # 大恢复: 描述 500
    assert heal_amount(_U(), 0x11) == 9999    # 超回复: 完全恢复
    assert HEAL_AMOUNT[0x26] == 200           # 恢复乐章: 200
