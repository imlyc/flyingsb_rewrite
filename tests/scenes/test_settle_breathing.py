"""大金刚延迟结算: 非最后敌人被砸死后, settle_pending 期间敌人应继续呼吸(待机)动画,
而非静止. 回归 _tick_unit_positions 跳过逻辑死单位导致 anim 冻结的 bug.
"""

from core.battle.data import BattleUnit
from scenes.battle.update import _tick_unit_positions


class _Scene:
    UNIT_TILES_PER_SEC = 6.0
    ANIM_EPSILON = 0.01

    def __init__(self, units):
        self.battle = type("B", (), {"all_units": units})()


def _unit(hp):
    u = BattleUnit(name="d", level=1, max_hp=20, hp=hp, max_mp=0, mp=0, sg=0,
                   attack=0, defence=0, agile=0, move=0, is_player=False)
    u.x, u.y = 3, 3
    u.snap_render()
    return u


def test_settle_pending_dead_unit_keeps_breathing():
    """逻辑已死 + settle_pending (视觉站立) → idle 动画继续推进."""
    u = _unit(hp=0)            # 已死
    u.settle_pending = True    # 但延迟结算, 视觉仍站立
    _tick_unit_positions(_Scene([u]), 40)
    assert u.anim.idle_time_ms == 40   # 呼吸继续


def test_truly_dead_unit_freezes():
    """已结算的死单位 (尸体) 不推进动画."""
    u = _unit(hp=0)            # 已死, 未 settle_pending = 尸体
    _tick_unit_positions(_Scene([u]), 40)
    assert u.anim.idle_time_ms == 0    # 冻结 (尸体不呼吸)
