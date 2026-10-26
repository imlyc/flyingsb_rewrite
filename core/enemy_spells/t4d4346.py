"""模板 FUN_004d4346 (5 招 沉默类: 10 施放沉默術, 75/147/241 使用賽亞安, 136 使用不利加得), reverse_engineering/enemy_spells_decomp.txt.
= 玩家 美娜 封魔 (core.mina_skills 0x10, 已按原版实录校准), 子实体直接复用 mina_skills._seal_hit / _seal_icon.

dispatcher: 渐暗 → 施法 seq → -100: 每目标一个控制体 FUN_004d4323 (think FUN_004d4132), +0x78 计数.
  控制体: age 8 起 16 次 (间隔 11,10,..,1,1..) → -250 + FUN_004d3f94 小 e_silenc 图标 (x±12, 行中心+1, z52±8, 帧 rand&3, 0xea);
          再 32t → -250 + FUN_004d4075 大图标 (帧 8, 0xea×3); 再 32t → -200, DAT_0086a764=1 (图标全灭), 自毁.
  -250: 受击 6557f4 (固定朝下, 不看朝向) + ef010 刺爆 655c10[DAT_006418e0] (=方向 0).
  -200: 只 +0x78-- (exe 无飘字; 我们这里 Spell.settle 做异常结算, 未中才飘 MISS).
  0x1e: 计数归零 + 目标受击完 → 0x28 渐亮 → 自毁.
"""
from __future__ import annotations

from core.enemy_spells.base import Spell
from core.mina_skills import _seal_hit, _seal_icon


def _ctrl_think(e, eng) -> None:
    """FUN_004d4132."""
    ud = e.user_data
    if 'seal' not in ud:
        return
    sp: Seal = ud['spell']
    b, t = sp.battle, ud['target']
    if ud['age'] == ud['next']:
        if ud['state'] == 0:
            _seal_hit(b, sp.coord, t)
            _seal_icon(b, sp.coord, t, big=False)
            ud['n'] += 1
            ud['next'] += max(0xc - ud['n'], 1)
            if ud['n'] > 0xf:
                ud['next'] = ud['age'] + 0x20
                ud['state'] = 10
        elif ud['state'] == 10:
            _seal_hit(b, sp.coord, t)
            _seal_icon(b, sp.coord, t, big=True)
            ud['next'] = ud['age'] + 0x20
            ud['state'] = 20
        else:
            sp.coord.user_data['icons_off'] = True          # DAT_0086a764 = 1
            sp.on_ctrl_done(t)
            eng.destroy(e)
            return
    ud['age'] += 1


class Seal(Spell):
    def on_cast_impact(self) -> None:
        self.coord.user_data['icons_off'] = False           # case -1: DAT_0086a764 = 0
        for t in self.targets:
            e = self.battle.engine.spawn(think_fn=_ctrl_think)
            e.flags = 0x800 | 0x10000
            e.user_data.update(kind='enemy_seal', projectile=True, seal=True, spell=self, target=t,
                               state=0, age=0, n=0, next=8)
            self.live += 1
        if not self.targets:
            self.finish()

    def on_ctrl_done(self, t) -> None:
        """-200."""
        self.live -= 1
        self.settle(t)
        if self.live <= 0:
            self.finish()


TEMPLATES = {0x4d4346: Seal}
