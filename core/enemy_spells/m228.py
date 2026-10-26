"""228 自爆 / 230 放出毒瓦斯: dispatcher FUN_004e58b0 / FUN_004e5ec8 (custom), reverse_engineering/enemy_spells_decomp.txt, 2026-10-26.

两者骨架相同 (部留系敌人, 施法 seq 都是 66c644[朝向] = 图 188 帧 3t/12t/5t, -100, 15t):
  case 0 渐暗 FUN_004d0cd8(1, 0x1e) → 10 挂施法 seq → 0x1e.
  -100   228: FUN_004e582c 爆炸 (施法者 x, y+1, z+24, seq 655eac 图 292 帧 0-10), 施法者清 0x40 (**隐身**), 播 0xc0 + 0xf6.
         230: FUN_004e5dc3 毒气 (施法者 x, y+1, z+12, 朝向偏移 上 y-9 / 下 y+9 / 左 x-12 / 右 x+12,
              seq 66c844[朝向] 图 332 12 帧各 2t), 播 0xb8.
         特效 think (FUN_004e57e8 / FUN_004e5d7f): seq 播完 → -200 自毁.
  -200   全部目标: FUN_004c4f20 + 受击 6557f0[目标朝向] + 两特效 (655c10[施法者朝向] + 655b18, 各轴 (rand&15)-8 抖动) + 飘字.
  0x1e   计数归零 → 0x28 渐亮 → 228 销毁施法者实体 (自爆者消失, 无死亡动画) → 自毁.
结算: 228 类别 4 = 固定伤害 core.enemy_moves.SELF_DESTRUCT_DMG[敌种] (同 combat._apply_enemy_special), 施法者 HP 归零;
230 走 Spell.settle (按招式类别).
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, fx, FP, _pos, _sfx, _dir, _unit_z
from core.enemy_spells.m203 import impact_fx, reset_hit
from core.enemy_spells.m205 import end_fx

CAST_228 = [  # @0x66c644
    [('fm', 188, 0, 3), ('fm', 188, 1, 12), ('fm', 188, 2, 5), ('jump', -100), ('fm', 188, 3, 15), ('exit',)],
    [('fm', 188, 6, 3), ('fm', 188, 7, 12), ('fm', 188, 8, 5), ('jump', -100), ('fm', 188, 9, 15), ('exit',)],
    [('fm', 188, 12, 3), ('fm', 188, 13, 12), ('fm', 188, 14, 5), ('jump', -100), ('fm', 188, 15, 15), ('exit',)],
    [('fm', 188, 18, 3), ('fm', 188, 19, 12), ('fm', 188, 20, 5), ('jump', -100), ('fm', 188, 21, 15), ('exit',)],
]
GAS = [  # @0x66c844
    [('fm', 332, 0, 2), ('fm', 332, 1, 2), ('fm', 332, 2, 2), ('fm', 332, 3, 2), ('fm', 332, 4, 2), ('fm', 332, 5, 2), ('fm', 332, 6, 2), ('fm', 332, 7, 2), ('fm', 332, 8, 2), ('fm', 332, 9, 2), ('fm', 332, 10, 2), ('fm', 332, 11, 2), ('exit',)],
    [('fm', 332, 12, 2), ('fm', 332, 13, 2), ('fm', 332, 14, 2), ('fm', 332, 15, 2), ('fm', 332, 16, 2), ('fm', 332, 17, 2), ('fm', 332, 18, 2), ('fm', 332, 19, 2), ('fm', 332, 20, 2), ('fm', 332, 21, 2), ('fm', 332, 22, 2), ('fm', 332, 23, 2), ('exit',)],
    [('fm', 332, 36, 2), ('fm', 332, 37, 2), ('fm', 332, 38, 2), ('fm', 332, 39, 2), ('fm', 332, 40, 2), ('fm', 332, 41, 2), ('fm', 332, 42, 2), ('fm', 332, 43, 2), ('fm', 332, 44, 2), ('fm', 332, 45, 2), ('fm', 332, 46, 2), ('fm', 332, 47, 2), ('exit',)],
    [('fm', 332, 24, 2), ('fm', 332, 25, 2), ('fm', 332, 26, 2), ('fm', 332, 27, 2), ('fm', 332, 28, 2), ('fm', 332, 29, 2), ('fm', 332, 30, 2), ('fm', 332, 31, 2), ('fm', 332, 32, 2), ('fm', 332, 33, 2), ('fm', 332, 34, 2), ('fm', 332, 35, 2), ('exit',)],
]
BOOM = [('fm', 292, 0, 1), ('fm', 292, 1, 1), ('fm', 292, 2, 2), ('fm', 292, 3, 2), ('fm', 292, 4, 2), ('fm', 292, 3, 2), ('fm', 292, 5, 3), ('fm', 292, 6, 4), ('fm', 292, 7, 5), ('fm', 292, 8, 5), ('fm', 292, 9, 5), ('fm', 292, 10, 5), ('exit',)]  # @0x655eac
GAS_OFF = ((0, -9), (0, 9), (-12, 0), (12, 0))


class _Burst(Spell):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.fired = False

    def cast_seq(self, d: int):
        return CAST_228[d]

    def on_cast_impact(self) -> None:
        if self.fired:
            return
        self.fired = True
        self.live += 1
        self.emit()

    def emit(self) -> None:
        """-100 子类实现: 生成特效, 播完调 self._burst_done."""

    def _burst_done(self) -> None:
        """-200."""
        self.live -= 1
        d = _dir(self.caster)
        for v in self.targets:
            reset_hit(v)
            impact_fx(self.battle, v, d)
        self.damage()
        self.finish()

    def damage(self) -> None:
        for v in self.targets:
            self.settle(v)


class SelfDestruct(_Burst):
    """228 自爆."""
    def emit(self) -> None:
        b, c = self.battle, self.caster
        x, y = _pos(c)
        end_fx(b, self._burst_done, x, y + FP, _unit_z(c) + 24 * FP, BOOM)
        c.cast_hidden = True                     # exe 施法者清 0x40 (不画)
        _sfx(b, 0xc0)
        _sfx(b, 0xf6)

    def damage(self) -> None:
        from core.battle import combat
        from core import enemy_moves as EM
        b, c = self.battle, self.caster
        dmg = EM.SELF_DESTRUCT_DMG.get(c.enemy_type, 44)
        c.suppress_hit_fx = True
        c.suppress_hit_reaction = True
        try:
            for v in self.targets:
                if v.alive:
                    combat.apply_damage(b, c, v, dmg, "", face_attacker=False)
        finally:
            c.suppress_hit_fx = False
            c.suppress_hit_reaction = False
        c.hp = 0
        b._log(f"{c.name} 自爆")


class PoisonGas(_Burst):
    """230 放出毒瓦斯."""
    def emit(self) -> None:
        b, c = self.battle, self.caster
        d = _dir(c)
        x, y = _pos(c)
        ox, oy = GAS_OFF[d]
        end_fx(b, self._burst_done, x + ox * FP, y + FP + oy * FP, _unit_z(c) + 12 * FP, GAS[d])
        _sfx(b, 0xb8)


MOVES = {228: SelfDestruct, 230: PoisonGas}
