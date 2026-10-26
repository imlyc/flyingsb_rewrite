"""246 火箭砲 (敌方 豬八戒): dispatcher FUN_004ff407 (custom), reverse_engineering/enemy_spells_decomp.txt, 2026-10-26.

跟玩家 猪八戒 技能 (core.pig_skills) 不是同一 dispatcher: 施法 seq 借用 回復豬彈 的 67439c[朝向] (cjupa_g0 1 发),
弹借用 火炎砲 的火球 67442c[朝向] + 火爆 fire02 656014, 但速度/结算顺序不同:
  case 0   **无渐暗**, 挂 67439c[朝向] → 10.
  -100     播 0x13a; FUN_004ff2d6(瞄准格, 施法者, 8, 6): 火球生在施法者 (x, y, z+48), 目标 = 瞄准格中心 (z 48),
           mode 0x31 匀速 上下 6 / 左右 8 px/t (只给朝向那一轴) → 0x14.
  弹 think FUN_004ff275: 两轴到 → 以**第一个目标**为源先发 -200 再发 -250, 自毁.
  -200     该目标飘字 (先于受击).
  -250     该目标 FUN_004c4f20 + 受击 6557f0 + 刺爆 655c10[施法者朝向] (x, y+400, z+448)
           + 火爆 FUN_004d0d7b(x + rand%12-6, y+24, z 72 + (rand&15)-8, 656014, 完发 -0x104) + 0x13b.
  0x14     计数归零 + 受击播完 → 自毁 (不渐亮).
只结算第一个目标 (exe 用 DAT_00869c48 当信号源).
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, fx, FP, _pos, _rand, _sfx, _cdbc2, _motion, _dir, _unit_z
from core.enemy_spells.m203 import SPARK, reset_hit
from core.enemy_spells.m205 import end_fx, tile_center
from core.pig_skills import FIRE_BALL_SEQS, FIRE_BURST_SEQ

CAST_246 = [  # @0x67439c
    [('fm', 14, 0, 12), ('move', 0, 8, 0, 0), ('jump', -100), ('fm', 14, 1, 3), ('move', 0, 4, 0, 2), ('move', 0, 2, 0, 1), ('fm', 14, 2, 3), ('fm', 14, 3, 3), ('move', 0, -14, 0, 0), ('fm', 14, 0, 0), ('exit',)],
    [('fm', 14, 4, 12), ('move', 0, -8, 0, 0), ('jump', -100), ('fm', 14, 5, 3), ('move', 0, -4, 0, 2), ('move', 0, -2, 0, 1), ('fm', 14, 6, 3), ('fm', 14, 7, 3), ('move', 0, 14, 0, 0), ('fm', 14, 4, 0), ('exit',)],
    [('fm', 14, 8, 12), ('move', 8, 0, 0, 0), ('jump', -100), ('fm', 14, 9, 3), ('move', 4, 0, 0, 2), ('move', 2, 0, 0, 1), ('fm', 14, 10, 3), ('fm', 14, 11, 3), ('move', -14, 0, 0, 0), ('fm', 14, 8, 0), ('exit',)],
    [('fm', 14, 12, 12), ('move', -8, 0, 0, 0), ('jump', -100), ('fm', 14, 13, 3), ('move', -4, 0, 0, 2), ('move', -2, 0, 0, 1), ('fm', 14, 14, 3), ('fm', 14, 15, 3), ('move', 14, 0, 0, 0), ('fm', 14, 12, 0), ('exit',)],
]
SFX_SHOT, SFX_HIT = 0x13a, 0x13b
SPEED = (6, 8)


def _ball_think(e, eng) -> None:
    ud = e.user_data
    if 'rocket' not in ud:
        return
    _cdbc2(e)
    if ud['m'] & 0x30:
        return
    sp: Rocket = ud['spell']
    sp.live -= 1
    sp.on_land()
    eng.destroy(e)


class Rocket(Spell):
    DIM = False
    FADE_IN = False

    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.fired = False

    def cast_seq(self, d: int):
        return CAST_246[d]

    def on_cast_impact(self) -> None:
        if self.fired:
            return
        self.fired = True
        b, c = self.battle, self.caster
        _sfx(b, SFX_SHOT)
        d = _dir(c)
        cur = getattr(c, 'pending_attack_cursor', None) or (c.x, c.y)
        tx, ty = tile_center(*cur)
        x, y = _pos(c)
        vud, vlr = SPEED
        vx, vy = ((0, -vud), (0, vud), (-vlr, 0), (vlr, 0))[d]
        fx(b, _ball_think, x, y, _unit_z(c) + 48 * FP, FIRE_BALL_SEQS[d], rocket=True, spell=self,
           **_motion(m=0x31, vx=vx * FP, vy=vy * FP, tx=tx, ty=ty, tz=48 * FP))
        self.live += 1

    def on_land(self) -> None:
        b = self.battle
        if self.targets:
            from core.pao_skills import hit_pos
            v = self.targets[0]
            self.settle(v)                                   # -200
            reset_hit(v)                                     # -250
            x, y = hit_pos(v)
            fx(b, None, x, y + 400 * FP, 448 * FP, SPARK[_dir(self.caster)])
            jz = ((_rand(b) & 15) - 8) * FP
            jx = (_rand(b) % 12 - 6) * FP
            self.live += 1
            end_fx(b, self._burst_done, x + jx, y + 24 * FP, 72 * FP + jz, FIRE_BURST_SEQ)
            _sfx(b, SFX_HIT)
        self._check_end()

    def _burst_done(self) -> None:
        self.live -= 1
        self._check_end()

    def _check_end(self) -> None:
        if self.live <= 0 and not self._finishing:
            self.finish()


MOVES = {246: Rocket}
