"""招式 35 使用任朋努 = custom dispatcher FUN_004ebfe5.

dispatcher: 0 渐暗 → 10 施法者挂单条 seq 6704c4 (不分朝向: fm_mode1 ps 表 184 帧 6 / 186 帧 6,7, 第 3 帧后 -100)
  -100: 每个目标 FUN_004ebf74 一团特效, 0x78++ → 0x1e.
        特效: 在目标 (x, y+1, z), seq 670520 (atlas 312 帧 0..10 抖动式 24 帧各 1t) + 播 0xcf;
        think FUN_004ebf02: age%20 == 0 播 0xbd; seq 播完 → -200 (源 = 目标) 自毁.
  -200: 受击 6557f0[目标自身朝向] + 刺爆 655c10[施法者朝向] + 飘字; 0x78--.
  0x1e: 0x78 / 0x7a / 受击 全清 → 0x28 渐亮 → 自毁.
实录校准 (wine/captures/en35_t13_F4720.log, 4 目标): 特效 +11 (48 t) / 位置 / -200 +59 吻合, 无需改动;
  渐亮差 2 t 来自飘字位数 (原版 3 位, 我们 4 位).
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, fx, FP, _pos, _sfx
from core.enemy_spells._ecommon import hit_unit

CAST = [('move', -4, 4, 0, 0), ('fm_mode1', 184, 6, 3), ('move', 4, -4, 0, 0), ('fm_mode1', 186, 6, 3),
        ('move', 0, -3, 0, 0), ('fm_mode1', 186, 7, 3), ('jump', -100), ('fm_mode1', 186, 7, 3), ('exit',)]   # 6704c4
FX_SEQ = [('fm', 312, f, 1) for f in (0, 1, 0, 2, 1, 2, 3, 2, 3, 4, 3, 4, 3, 4, 5, 6, 7, 6, 7, 8, 7, 8, 9, 10)] \
    + [('exit',)]                                                                                              # 670520
SFX_START, SFX_TICK = 0xcf, 0xbd


def _fx_think(e, eng) -> None:
    """FUN_004ebf02."""
    ud = e.user_data
    if 'renpeng' not in ud:
        return
    sp = ud['spell']
    if ud['age'] % 20 == 0:
        _sfx(sp.battle, SFX_TICK)
    ud['age'] += 1
    if not e.is_playing():
        sp.on_fx_done(ud['victim'])
        eng.destroy(e)


class RenPeng(Spell):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.launched = False

    def cast_seq(self, d):
        return CAST

    def on_cast_impact(self) -> None:
        self.launched = True
        for v in self.targets:
            x, y = _pos(v)
            fx(self.battle, _fx_think, x, y + FP, 0, FX_SEQ, renpeng=True, spell=self, victim=v, age=0)
            _sfx(self.battle, SFX_START)
            self.live += 1

    def on_fx_done(self, v) -> None:
        """-200."""
        self.live -= 1
        hit_unit(self, v)
        self.settle(v)

    def think(self) -> None:
        if self.launched and self.live == 0 and not self._finishing:
            self.finish()


MOVES = {35: RenPeng}
