"""招式 32 使用沙得喜 (吸血) = custom dispatcher FUN_004ebc0d.

dispatcher: 0 渐暗 → 10 播 0xbc + 施法者挂 670264[朝向] (atlas 56: 前冲 3 帧 → -100 → -105 → 2 帧 + 定格 15t → 退回 → -110)
  -100: 目标0 复位 + 受击 6557f0[目标自身朝向] (**无刺爆**) + 飘字 (预算伤害), 0x7a++;
        FUN_004d074e(施法者, DAT_007da1ec) 施法者头上回复数字, 0x7a++ → 0x1e.
  -20: 0x7a--.  0x1e: 0x7a == 0 → 0x28 渐亮 → 自毁 (不等受击 seq).
DAT_007da1ec (FUN_004a6efe 敌方分支, 招式 0x20 / 0x7f): 吸血量 = 造成的伤害, 但不超过施法者 MaxHP - 当前 HP;
  施法者 HP += 吸血量. 数值层 (core.battle.formulas) 没实现这一项, 这里在演出结算里补上 (建议日后挪进 formulas).
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, _sfx

def _cast(d: int) -> list[tuple]:
    """670264[d]: 上下每步 3px / 左右 4px, 先冲 6px, 退回 21 / 26px."""
    sx, sy = ((0, -1), (0, 1), (-1, 0), (1, 0))[d]
    st, back, f = (4, 26, d * 6) if d >= 2 else (3, 21, d * 6)

    def mv(n):
        return ('move', sx * n, sy * n, 0, 0)
    return [mv(6), ('fm', 56, f, 3), mv(st), ('fm', 56, f + 1, 3), mv(st), ('fm', 56, f + 2, 3), mv(st),
            ('jump', -100), ('jump', -105), ('fm', 56, f + 3, 3), mv(st), ('fm', 56, f + 4, 3), mv(st),
            ('fm', 56, f + 5, 15), mv(-back), ('fm', 56, f, 0), ('jump', -110), ('exit',)]


CAST = [_cast(d) for d in range(4)]
SFX_CAST = 0xbc


class ShaDeXi(Spell):
    def cast_seq(self, d):
        _sfx(self.battle, SFX_CAST)
        return CAST[d]

    def on_cast_impact(self) -> None:
        from core.battle import combat
        b, c = self.battle, self.caster
        if self.targets:
            v = self.targets[0]
            if v.alive:
                combat.set_reaction(v, "hit", None)
            before = v.hp
            self.settle(v)
            dmg = max(0, before - v.hp)
            gain = min(dmg, max(0, c.max_hp - c.hp))
            if c.alive:
                c.hp += gain
                combat.push_damage_event(b, c, combat.DamageEvent(gain, c.hp, c.x, c.y, heal=True))
                b._log(f"{c.name} 吸血 {gain} HP")
        self.finish()


MOVES = {32: ShaDeXi}
