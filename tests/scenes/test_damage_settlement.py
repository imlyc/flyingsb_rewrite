"""伤害结算 (原版式: signal 触发 + working/committed 提交):
  - 受击反应**结束** → commit HP (工作缓冲→显示; 存活同步真值, 死亡保留旧值). 早于闪烁.
  - 伤害数字进 flash → 自驱信号 → 触发死亡动画 + 放行视觉.
  - settle_batch (大金刚) 跳过, 等批量结算.
"""

from core.battle.data import BattleUnit
from core.sprites.base import TILE_W, TILE_H
from scenes.battle.update import _tick_reactions, _tick_damage_signals


class _FloatStub:
    def __init__(self, unit, flashing):
        self.target_unit = unit
        self.heal = False
        self._flash = flashing
        self._fired = False

    def take_flash_signal(self, now):
        if self._flash and not self._fired:
            self._fired = True
            return True
        return False


class _Scene:
    def __init__(self, units, floats):
        self.battle = type("B", (), {"all_units": units})()
        self._floats = floats


def _enemy(x, y, hp=20):
    u = BattleUnit(name="d", level=1, max_hp=20, hp=hp, max_mp=0, mp=0, sg=0,
                   attack=0, defence=0, agile=0, move=0, is_player=False)
    u.x, u.y = x, y
    return u


def _hurt(u, old, new):
    u.hp = new
    u.shown_hp_override = old
    u.settle_pending = True
    u.reaction_seq = [("set_frame", 6, 0, 1)]   # 受击反应进行中
    u.reaction_step_idx = 99                     # 已到末尾 → advance 一步即结束


def test_commit_hp_on_reaction_end_before_flash():
    """存活敌人: 受击反应结束 → HP 显示更新 (commit), 早于闪烁."""
    d = _enemy(3, 4); _hurt(d, 20, 5)
    assert d.display_hp == 20
    _tick_reactions(_Scene([d], []), 40)         # 反应结束 → commit
    assert d.reaction_seq is None
    assert d.display_hp == 5                      # 提交后显示真值
    assert d.display_weakened is True


def test_dying_enemy_keeps_old_hp_after_commit():
    """致死敌人: commit 不提交, 保留受击前旧值 (死亡闪烁期不显 0)."""
    d = _enemy(2, 2, hp=10); _hurt(d, 10, 0)
    _tick_reactions(_Scene([d], []), 40)
    assert d.display_hp == 10                     # 保留旧值


def test_flash_signal_triggers_death():
    """致死敌人: 数字闪烁信号 → 放行视觉 + 启动死亡动画."""
    d = _enemy(1, 1, hp=10); _hurt(d, 10, 0)
    sc = _Scene([d], [])
    _tick_reactions(sc, 40)                       # 反应结束 (death 仍未启动, 等闪烁)
    assert d.death_anim_time_ms < 0 and d.settle_pending is True
    sc._floats = [_FloatStub(d, flashing=True)]
    _tick_damage_signals(sc, 0)                   # 闪烁信号
    assert d.settle_pending is False
    assert d.death_anim_time_ms == 0              # 死亡动画启动


def test_batch_unit_skips_reaction_commit_and_flash():
    """大金刚 settle_batch: 反应结束不 commit, 闪烁信号不触发死亡 (等批量)."""
    d = _enemy(2, 2, hp=10); _hurt(d, 10, 0); d.settle_batch = True
    sc = _Scene([d], [_FloatStub(d, flashing=True)])
    _tick_reactions(sc, 40)
    assert d.display_hp == 10 and d.settle_pending is True
    _tick_damage_signals(sc, 0)
    assert d.settle_pending is True and d.death_anim_time_ms < 0
