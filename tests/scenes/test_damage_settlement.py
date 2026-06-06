"""伤害结算门控 update._tick_damage_settlement (原版两节点, 都在受击反应结束后):
  (1) HP 数字减少: 伤害数字"落定" (rise 结束→hold) 时 — 早于闪烁. 存活显新值, 死亡保留旧值.
  (2) 虚弱/死亡视觉: 伤害数字进 flash 时放行.
settle_batch (大金刚) 跳过, 等批量结算.
"""

from core.battle.data import BattleUnit
from core.sprites.base import TILE_W, TILE_H
from scenes.battle.update import _tick_damage_settlement


class _FloatStub:
    def __init__(self, ux, uy, landed, flashing):
        self.world_x = ux * TILE_W + TILE_W // 2
        self.world_y = uy * TILE_H + TILE_H // 2
        self._landed = landed
        self._flash = flashing

    def landed_at(self, now):
        return self._landed

    def flash_started_at(self, now):
        return self._flash


class _Scene:
    def __init__(self, units, floats):
        self.battle = type("B", (), {"all_units": units})()
        self._floats = floats


def _hurt(u, old, new):
    u.hp = new
    u.shown_hp_override = old
    u.settle_pending = True


def _enemy(x, y, hp=20):
    u = BattleUnit(name="d", level=1, max_hp=20, hp=hp, max_mp=0, mp=0, sg=0,
                   attack=0, defence=0, agile=0, move=0, is_player=False)
    u.x, u.y = x, y
    return u


def test_hp_display_updates_at_landing_before_flash():
    """存活敌人: 数字落定 (未闪) → HP 显示更新; 但虚弱/死亡视觉仍等闪烁."""
    d = _enemy(3, 4); _hurt(d, 20, 5)
    # 数字还没落定 → 不更新
    _tick_damage_settlement(_Scene([d], [_FloatStub(3, 4, landed=False, flashing=False)]), 0)
    assert d.display_hp == 20 and d.settle_pending is True
    # 落定 (未闪) → HP 显示更新, 但 settle_pending 仍在 (虚弱/死亡视觉未放行)
    _tick_damage_settlement(_Scene([d], [_FloatStub(3, 4, landed=True, flashing=False)]), 0)
    assert d.display_hp == 5
    assert d.settle_pending is True
    # 闪烁 → 视觉放行
    _tick_damage_settlement(_Scene([d], [_FloatStub(3, 4, landed=True, flashing=True)]), 0)
    assert d.settle_pending is False


def test_dying_enemy_keeps_old_hp_through_settlement():
    """致死敌人: 落定/闪烁都不显 0, 保持受击前旧值."""
    d = _enemy(2, 2, hp=10); _hurt(d, 10, 0)
    _tick_damage_settlement(_Scene([d], [_FloatStub(2, 2, landed=True, flashing=True)]), 0)
    assert d.display_hp == 10          # 保留旧值, 不显 0
    assert d.settle_pending is False   # 死亡视觉放行


def test_settle_waits_for_reaction_to_end():
    d = _enemy(1, 1); _hurt(d, 20, 0)
    d.reaction_seq = [("dummy",)]
    _tick_damage_settlement(_Scene([d], [_FloatStub(1, 1, landed=True, flashing=True)]), 0)
    assert d.settle_pending is True and d.display_hp == 20


def test_batch_unit_skipped_by_single_settlement():
    """大金刚 settle_batch unit 不在落定/闪烁时自动结算 (等批量)."""
    d = _enemy(2, 2); _hurt(d, 20, 0); d.settle_batch = True
    _tick_damage_settlement(_Scene([d], [_FloatStub(2, 2, landed=True, flashing=True)]), 0)
    assert d.settle_pending is True and d.display_hp == 20
