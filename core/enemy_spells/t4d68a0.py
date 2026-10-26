"""模板 FUN_004d68a0 (11 招: 巨雷壓頂 等落雷类), reverse_engineering/enemy_spells_decomp.txt.

dispatcher: 渐暗 → 施法 seq → -100: 0x1e 每 8t (dispatcher age%8==0) 给下一个目标放一道雷 (FUN_004d6835):
  雷 = 目标位置 seq 656acc (esund 293 帧 0..5 各 1t) + 0xf6; think FUN_004d67c8: age==2 → -250, seq 完 → -200 并自毁.
  -250: 目标受击 6557f0[目标朝向] + ef010 刺爆 655c10[施法者朝向].
  -200: 飘字 + FUN_004d66cc 4 粒火花 (ds_mag13 230 帧 5..11 各 1t, seq 656b0c): 绕目标 mode 0x32 (x = cx + sin φ·r),
        φ0 = (rand&0xff)<<6, 每粒 +0x4000; 半径每 t +4+rand%4 (两轴各掷); 末粒播完 → -300 计数.
  0x28: 全部放完 + 飘字完 + -300 计满 + 目标受击完 → 0x32 渐亮 → 自毁.
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, fx, FP, _pos, _rand, _sfx, _c3211, _motion

ESUND, DS_MAG13 = 293, 230
BOLT_SEQ = [('fm', ESUND, f, 1) for f in range(6)] + [('exit',)]                  # 656acc
SPARK_SEQ = [('fm', DS_MAG13, f, 1) for f in range(5, 12)] + [('exit',)]          # 656b0c
SFX_BOLT = 0xf6
INTERVAL = 8


def _bolt_think(e, eng) -> None:
    """FUN_004d67c8."""
    ud = e.user_data
    if 'bolt' not in ud:
        return
    sp: Thunder = ud['spell']
    ud['age'] += 1
    if ud['age'] == 2:
        sp.hit(ud['victim'])
    if not e.is_playing():
        sp.on_bolt_done(ud['victim'])
        eng.destroy(e)


def _spark_think(e, eng) -> None:
    """FUN_004d661e."""
    ud = e.user_data
    if 'spark' not in ud:
        return
    sp: Thunder = ud['spell']
    b = sp.battle
    ud['rx'] += 4 + (_rand(b) & 3)
    ud['ry'] += 4 + (_rand(b) & 3)
    _c3211(e)
    if not e.is_playing():
        if ud['last']:
            sp.completed += 1
        eng.destroy(e)


class Thunder(Spell):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.spawned = 0
        self.completed = 0
        self.casting = False

    def on_cast_impact(self) -> None:
        self.spawned = 0
        self.casting = True

    def think(self) -> None:
        if not self.casting:
            return
        if self.spawned < len(self.targets):
            if self.age % INTERVAL == 0:
                v = self.targets[self.spawned]
                self.spawned += 1
                x, y = _pos(v)
                fx(self.battle, _bolt_think, x, y, 0, BOLT_SEQ, bolt=True, spell=self, victim=v, age=0)
                _sfx(self.battle, SFX_BOLT)
                self.live += 1
            return
        if self.completed >= len(self.targets):
            self.casting = False
            self.finish()

    def on_bolt_done(self, v) -> None:
        """-200."""
        self.live -= 1
        self.settle(v)
        b = self.battle
        x, y = _pos(v)
        phi = ((_rand(b) & 0xff) * 0x10000) >> 10
        for i in range(4):
            e = fx(b, _spark_think, x, y, 0, SPARK_SEQ, spark=True, spell=self, last=(i == 3),
                   **_motion(m=0x32, tx=x, ty=y, px=phi, py=phi))
            _c3211(e)
            phi += 0x4000


TEMPLATES = {0x4d68a0: Thunder}
